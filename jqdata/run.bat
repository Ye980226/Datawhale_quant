@echo off



set PYTHONPATH=%cd%


echo create jaqs m1 index
python jqdata.py create


echo update jaqs m1 data
python jqdata.py update publish


pause