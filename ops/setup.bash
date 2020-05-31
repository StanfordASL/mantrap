#!/bin/bash

# Setup environment variables.
PROJECT_HOME="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
EXTERNAL_HOME="$PROJECT_HOME/third_party"
VIRTUAL_ENV=".venv_mantrap"
echo 'Setting up project ...'

# Login to virtual environment.
cd "${PROJECT_HOME}" || return
if [[ ! -d "${VIRTUAL_ENV}" ]]; then
    echo 'Creating virtual environment ...'
    mkdir "${VIRTUAL_ENV}"
    pip3 install virtualenv
    virtualenv -p python3 "${VIRTUAL_ENV}"
fi
# shellcheck source=.venv_muresco/bin/activate
source "${PROJECT_HOME}"/"${VIRTUAL_ENV}"/bin/activate

# Install self-python-package.
echo $'\nInstalling package ...'
cd "${PROJECT_HOME}" || return
pip3 install -r "${PROJECT_HOME}"/ops/requirements.txt
echo mantrap > "${VIRTUAL_ENV}"/lib/python3.7/site-packages/mantrap.pth
echo mantrap_evaluation > "${VIRTUAL_ENV}"/lib/python3.7/site-packages/mantrap_evaluation.pth

# Install external libraries requirements.
pip3 install -r "${EXTERNAL_HOME}"/GenTrajectron/requirements.txt

# Create output directory.
mkdir "${PROJECT_HOME}"/outputs

cd "${PROJECT_HOME}" || return
echo $'\nSuccessfully set up project !'
