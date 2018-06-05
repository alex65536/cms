#!/bin/bash

scp -r cmscontrib/loaders judge@judge:/home/judge/cms/cms/cmscontrib/loaders

ssh -t judge@judge "./cmsrebuild.sh && ./importtest.sh"
