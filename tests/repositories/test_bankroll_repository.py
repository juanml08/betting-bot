from datetime import date

from app.db.repositories.bankroll_repository import BankrollRepository


def test_current_balance_with_no_transactions_equals_initial_bankroll(db_session):
    balance = BankrollRepository(db_session).current_balance(1000.0)

    assert balance == 1000.0


def test_record_persists_transaction_and_updates_balance(db_session):
    repo = BankrollRepository(db_session)

    tx = repo.record(
        occurred_on=date(2026, 1, 5),
        amount=-50.0,
        reason="bet_placed",
        balance_after=950.0,
    )
    db_session.commit()

    assert tx.id is not None
    assert float(tx.amount) == -50.0
    assert repo.current_balance(1000.0) == 950.0


def test_current_balance_sums_all_transactions(db_session):
    repo = BankrollRepository(db_session)
    repo.record(occurred_on=date(2026, 1, 1), amount=-50.0, reason="bet_placed", balance_after=950.0)
    repo.record(occurred_on=date(2026, 1, 2), amount=100.0, reason="bet_won", balance_after=1050.0)
    db_session.commit()

    assert repo.current_balance(1000.0) == 1050.0


def test_list_transactions_orders_by_occurred_on(db_session):
    repo = BankrollRepository(db_session)
    repo.record(occurred_on=date(2026, 1, 10), amount=100.0, reason="bet_won", balance_after=1100.0)
    repo.record(occurred_on=date(2026, 1, 1), amount=-50.0, reason="bet_placed", balance_after=950.0)
    db_session.commit()

    transactions = repo.list_transactions()

    assert [t.occurred_on for t in transactions] == [date(2026, 1, 1), date(2026, 1, 10)]


def test_record_links_related_bet_id(db_session):
    repo = BankrollRepository(db_session)

    tx = repo.record(
        occurred_on=date(2026, 1, 5),
        amount=-50.0,
        reason="bet_placed",
        balance_after=950.0,
        related_bet_id=None,
    )
    db_session.commit()

    assert tx.related_bet_id is None
