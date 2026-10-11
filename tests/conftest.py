import pytest

from telebazaar import db


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path)
    db.migrate(c)
    yield c
    c.close()
