import pytest
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool

from app import models


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def make_account(session):
    def _make(account_number="ACC1", holder_name="TEST HOLDER", bank_name="Test Bank"):
        account = models.Account(
            holder_name=holder_name, account_number=account_number,
            bank_name=bank_name, account_type="savings",
        )
        session.add(account)
        session.commit()
        session.refresh(account)
        return account
    return _make


@pytest.fixture
def make_txn(session):
    counter = {"page": 1, "row": 0}

    def _make(account, statement_id, txn_date, description, debit=None, credit=None, balance=None, document_id=1):
        counter["row"] += 1
        txn = models.Transaction(
            statement_id=statement_id,
            account_id=account.id,
            document_id=document_id,
            page=1,
            row_index=counter["row"],
            txn_date=txn_date,
            description=description,
            description_norm=description.upper(),
            debit=debit,
            credit=credit,
            balance=balance,
            raw_text=description,
        )
        session.add(txn)
        session.commit()
        session.refresh(txn)
        return txn
    return _make
