#!/bin/bash

PROJECT_HOME="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"/..
# shellcheck source=.venv_muresco/bin/activate
source "${PROJECT_HOME}"/.venv_muresco/bin/activate

rm -r "${PROJECT_HOME}"/test/cache
mkdir "${PROJECT_HOME}"/test/cache
pytest "${PROJECT_HOME}"/test/*.py -vv