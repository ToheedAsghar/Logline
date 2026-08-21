#!/bin/bash
cd /Users/toheed.asghar/Documents/projects/logline/.worktrees/tracker-desktop-app
export PYTHONPATH=$(pwd)
/Users/toheed.asghar/Documents/projects/logline/.worktrees/tracker-desktop-app/tracker/test_env/bin/python tracker/ax_probe.py > /tmp/true_negative.log 2>&1
