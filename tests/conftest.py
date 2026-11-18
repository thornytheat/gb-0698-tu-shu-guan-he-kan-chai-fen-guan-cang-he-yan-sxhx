import os
import shutil
from pathlib import Path

DATA_DIR = "/tmp/serial-holdings-pytest"
os.environ["DATA_DIR"] = DATA_DIR
# 规则演进后旧批次快照不再可信，测试会话开始清空本地 SQLite，避免 INSERT OR IGNORE 命中历史结果
shutil.rmtree(DATA_DIR, ignore_errors=True)

import pytest
from app.pipeline import run, sample_text

@pytest.fixture
def sample(): return sample_text()

@pytest.fixture
def result(sample): return run(sample)
