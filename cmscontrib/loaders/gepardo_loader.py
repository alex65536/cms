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

import os
import json
import logging
import datetime

from cms import SCORE_MODE_MAX, SCORE_MODE_MAX_TOKENED_LAST
from cms.db import Contest, User, Task, Statement, Attachment, \
    Team, SubmissionFormatElement, Dataset, Manager, Testcase
from cms.grading.languagemanager import LANGUAGES, HEADER_EXTS

from .base_loader import ContestLoader, TaskLoader

logger = logging.getLogger(__name__)


class GepardoLoader(ContestLoader, TaskLoader):
    short_name = 'gepardo_loader'
    description = 'Loader for tasks in gepardo format'

    @staticmethod
    def detect(path):
        return os.path.exists(os.path.join(path, "problem-list.txt")) or \
            os.path.exists(os.path.join(path, "problem.json")) or \
            os.path.exists(os.path.join(path, "contest.json"))

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

    def __load_contest_json(self, path):
        return json.loads(open(os.path.join(path, 'contest.json'), 'r').read())

    def __load_contest(self, path):
        contest_json = self.__load_contest_json(path)
        return contest_json['contest']

    def __load_token_submission_info(self, path, args):
        contest = self.__load_contest(path)
        token_count = contest['tokenCount']
        if token_count == -1:
            args['token_mode'] = 'infinite'
        elif token_count == 0:
            args['token_mode'] = 'disabled'
        else:
            args['token_mode'] = 'finite'
            args['token_max_number'] = token_count
            args['token_min_interval'] = datetime.timedelta()
            args['token_gen_initial'] = token_count
            args['token_gen_number'] = 0
            args['token_gen_interval'] = datetime.timedelta(minutes=1)
            args['token_gen_max'] = token_count
        args['max_submission_number'] = contest['submissionCount']

    def get_contest(self):
        # Check for required files
        if not (
            self.__require_file("contest.json") and
            self.__require_file("problem-list.txt")
        ):
            return None
        # Load name and description
        contest = self.__load_contest(self.path)
        args = {}
        args['name'] = contest['name']
        args['description'] = contest['description']
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

    def __add_tests(self, folder, task, args, start_with, is_public):
        test_dir = os.path.join(self.path, folder)
        testid = start_with
        testnum = 1
        while True:
            infile = os.path.join(test_dir, "%d.in" % testnum)
            outfile = os.path.join(test_dir, "%d.out" % testnum)
            if not (os.path.exists(infile) and os.path.exists(outfile)):
                break
            logger.info("Adding test %d from %s" % (testnum, folder))
            input_digest = self.file_cacher.put_file_from_path(infile,
                "Input %d for task %s" % (testid, task.name))
            output_digest = self.file_cacher.put_file_from_path(outfile,
                "Output %d for task %s" % (testid, task.name))
            args['testcases'] += [
                Testcase('%03d' % testid, is_public, input_digest, output_digest)]
            testid += 1
            testnum += 1
        return testid

    def get_task(self, get_statement=True):
        # Name
        name = os.path.split(self.path)[1]
        # Check for required files
        if not self.__require_file("problem.json"):
            return None
        # Load JSON
        problem_json = json.loads(open(os.path.join(self.path, 'problem.json'), 'r').read())
        problem = problem_json['problem']
        # Load info
        args = {}
        args['name'] = name
        args['title'] = problem['name']
        logger.info("Loading parameters for task %s.", name)
        # Load statement
        if get_statement:
            language = 'ru'
            path = os.path.join(self.path, '..', '..', 'statements', name + '.pdf')
            if os.path.exists(path):
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
        self.__load_token_submission_info(os.path.join(self.path, '..', '..'), args)
        args['score_mode'] = SCORE_MODE_MAX_TOKENED_LAST
        task = Task(**args)
        # Load dataset info
        args = {}
        args['task'] = task
        args['description'] = ''
        args['autojudge'] = False
        args['time_limit'] = problem['timeLimit']
        args['memory_limit'] = problem['memoryLimit']
        args['managers'] = []
        # Add checker
        checker_src = os.path.join(self.path, 'checker.cpp')
        checker_exe = os.path.join(self.path, 'checker')
        if os.path.exists(checker_src):
            logger.info("Checker found, compiling")
            os.system(
                "g++ -x c++ -O2 -static -DCMS -o %s %s" %
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
        # Add testcases
        args['testcases'] = []
        pretest_cnt = self.__add_tests('pretests', task, args, 0, True)
        self.__add_tests('tests', task, args, pretest_cnt, False)
        # Add input/output
        infile_param = problem['input']
        outfile_param = problem['output']
        args["task_type"] = "Batch"
        args["task_type_parameters"] = \
            '["%s", ["%s", "%s"], "%s"]' % \
            ("alone", infile_param, outfile_param, evaluation_param)
        if problem['scoreType'] == 'subtask':
            subtasks = [[0, pretest_cnt]] + problem['subtasks']
            args['score_type'] = 'GroupMin'
            args['score_type_parameters'] = str(subtasks)
        elif problem['scoreType'] == 'byTest':
            args['score_type'] = 'Sum'
            args['score_type_parameters'] = str(problem['cost'])
        else:
            logger.critical('Unknown scoring type: %s' % problem['scoreType'])
        # Finalize dataset
        dataset = Dataset(**args)
        task.active_dataset = dataset
        # Import was successful
        logger.info("Task parameters loaded.")
        return task

    def task_has_changed(self):
        return True

    def contest_has_changed(self):
        return True
