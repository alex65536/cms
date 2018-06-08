#!/bin/bash

rsync -trl --del --progress cmscontrib/loaders/ judge@judge:/home/judge/cms/cms/cmscontrib/loaders/

ssh -t judge@judge "./cmsrebuild.sh && ./cmsimporttest.sh"
