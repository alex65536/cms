#!/usr/bin/env python2
# -*- coding: utf-8 -*-

# Contest Management System - http://cms-dev.github.io/
# Copyright © 2013 Giovanni Mascellani <mascellani@poisson.phc.unipi.it>
# Copyright © 2014-2015 William Di Luigi <williamdiluigi@gmail.com>
# Copyright © 2018 Alexander Kernozhitsky <sh200105@mail.ru>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import json

from cms import SCORE_MODE_MAX, SCORE_MODE_MAX_TOKENED_LAST
from cms.db import Contest, User, Task, Statement, Attachment, \
    Team, SubmissionFormatElement, Dataset, Manager, Testcase
from cms.grading.languagemanager import LANGUAGES, HEADER_EXTS
from cmscommon.datetime import make_datetime
from cmscontrib import touch

from .base_loader import ContestLoader, TaskLoader


class GepardoLoader(TaskLoader, ContestLoader):
    short_name = 'gepardo_loader'
    description = 'Loader for tasks in gepardo format'

    @staticmethod
    def detect(path):
        return os.path.exists("problem-list.txt") or \
            os.path.exists("problem.json") or \
            os.path_exists("contest.json")

    def get_task_loader(self, taskname):
        return GepardoLoader(
            os.path.join(self.path, 'problems', taskname),
            self.file_cacher
        )

    def __require_file(self, fname):
        if not os.path.exists(os.path.join(self.path, fname)):
            logger.critical('File missing: "%s"' % (fname))
            return False
        return True

    def __load_contest_json(path):
        return json.loads(open(os.path.join(path, 'contest.json'), 'r').read())

    def __load_token_submission_info(path, args):
        contest = __load_contest_json(path)
        token_count = contest['tokenCount']
        if token_count == -1:
            args['token_mode'] = 'infinite'
        elif token_count == 0:
            args['token_mode'] = 'disabled'
        else:
            args['token_mode'] = 'finite'
            args['token_max_number'] = token_count
            args['token_min_interval'] = 0
            args['token_gen_initial'] = token_count
            args['token_gen_number'] = 0
            args['token_gen_interval'] = 0
            args['token_gen_max'] = token_count
        args['max_submission_number'] = contest['submissionCount']

    def get_contest(self):
        # Check for required files
        if not (
            __require_file("contest.json") and
            __require_file("problem-list.txt")
        ):
            return None
        # Load name and description
        contest = __load_contest_json(self.path)
        args = {}
        args['name'] = contest['name']
        args['description'] = ''
        logger.info("Loading parameters for contest %s.", args['name'])
        args['token_mode'] = 'infinite'
        # Tasks
        tasks = list(
            map((lambda x: x[:-1]),
            open(os.path.join(self.path, 'problem-list.txt'), 'r'))
        )
        # Import was successful
        logger.info("Contest parameters loaded.")
        return Contest(**args), tasks, []

    def get_task(self, get_statement=True):
        # Name
        name = os.path.split(self.path)[1]
        # Check for required files
        if not __require_file("problem.json"):
            return None
        # Load JSON
        problem = json.loads(open('problem.json', 'r').read())
        # Load info
        args = {}
        args['name'] = name
        args['title'] = problem['name']
        logger.info("Loading parameters for task %s.", name)
        # Load statement
        if get_statement:
            language = 'ru'
            path = os.path.join(self.path, '..', '..', 'statements', name + '.pdf')
            if os.path_exists(path):
                digest = self.file_cacher.put_file_from_path(
                        path,
                        "Statement for task %s (lang: %s)" % (name, language)
                )
                args['statements'] = [Statement(language, digest)]
                args['primary_statements'] = '["%s"]' % (language)
            else:
                logger.error('No statements found for problem "%s"' % (name))
        # Load other properties
        args['submission_format'] = [SubmissionFormatElement('%s.%%l' % name)]
        __load_token_submission_info(os.path.join(self.path, '..', '..'), args)
        args['score_mode'] = SCORE_MODE_MAX_TOKENED_LAST
        task = Task(**args)
        # Load dataset info
        args = {}
        args['task'] = task
        args['description'] = ''
        args['autojudge'] = False
        args['time_limit'] = problem['timeLimit']
        args['memory_limit'] = problem['memoryLimit']
        # Add checker
        checker_src = os.path.join(self.path, 'checker.cpp')
        checker_exe = os.path.join(self.path, 'checker')
        if os.path.exists(checker_src):
            logger.info("Checker found, compiling")
            os.system(
                "g++ -x c++ -O2 -static -o %s - %s" %
                (checker_exe, checker_src)
            )
            digest = self.file_cacher.put_file_from_path(
                checker_exe,
                "Manager for task %s" % name
            )
            args['managers'] += [Manager('checker', digest)]
            evaluation_param = 'comparator'
        else:
            logger.info("Checker not found, using diff")
            evaluation_param = 'diff'
        # Add input/output
        infile_param = problems['input']
        outfile_param = problems['output']
        args["task_type"] = "Batch"
        args["task_type_parameters"] = \
            '["%s", ["%s", "%s"], "%s"]' % \
            ("alone", infile_param, outfile_param, evaluation_param)
        if problem['scoreType'] == 'subtask':
            args['score_type'] = "GroupMin"
            args['score_type_parameters'] = str(problem['subtasks'])
        elif problem['scoreType'] == 'byTest':
            args['score-type'] = 'Sum'
            args['score_type_parameters'] = str(problem['cost'])
        else:
            logger.error('Unknown scoring type: %s' % problem['scoreType'])
        # Add testcases
        args['testcases'] = []
        test_dir = os.path.join(self.path, 'tests')
        testid = 0
        while True:
            testid += 1
            infile = os.path.join(test_dir, "%d.in" % testid)
            outfile = os.path.join(test_dir, "%d.out" % testid)
            if not (os.path.exists(infile) and os.path.exists(outfile)):
                break
            logger.info("Adding test %d", testid)
            input_digest = self.file_cacher.put_file_from_path(infile,
                "Input %d for task %s" % (testid, task.name))
            output_digest = self.file_cacher.put_file_from_path(outfile,
                "Output %d for task %s" % (testid, task.name))
            args['testcases'] += [
                Testcase('%03d' % testid, False, input_digest, output_digest)]
        dataset = Dataset(**args)
        task.active_dataset = dataset
        # Import was successful
        logger.info("Task parameters loaded.")
        return task

        def task_has_changed(self):
            return True

        def contest_has_changed(self):
            return True
