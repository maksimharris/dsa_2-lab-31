from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index
from sqlalchemy import MetaData, Numeric, Table, Text

metadata = MetaData()

accounts = Table(
    "accounts", metadata,
    Column("customer_id", Text, primary_key=True),
    Column("balance", BigInteger, nullable=False),
)

operations = Table(
    "operations", metadata,
    Column("operation_id", Text, primary_key=True),
    Column("type", Text, nullable=False),
    Column("customer_id", Text, ForeignKey("accounts.customer_id"), nullable=False),
    Column("store_id", Text, nullable=False),
    Column("check_number", Text, nullable=False),
    Column("amount", Numeric),
    Column("points_delta", BigInteger, nullable=False),
    Column("balance_after", BigInteger, nullable=False),
    Column("status", Text, nullable=False),
    Column("reject_reason", Text),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("processed_at", DateTime(timezone=True), nullable=False),
)
Index("operations_history", operations.c.customer_id, operations.c.processed_at)
Index("operations_receipt", operations.c.check_number)

EVENT_FIELDS = (
    "operation_id", "type", "customer_id", "store_id", "status",
    "points_delta", "balance_after", "reject_reason", "processed_at",
)


def to_event(row):
    event = {name: row[name] for name in EVENT_FIELDS}
    event["processed_at"] = row["processed_at"].isoformat()
    return event
