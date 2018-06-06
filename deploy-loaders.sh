#!/bin/bash

scp -r cmscontrib/loaders judge@judge:/home/judge/cms/cms/cmscontrib/

ssh -t judge@judge "./cmsrebuild.sh && ./cmsimporttest.sh"
