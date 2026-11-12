from decimal import Decimal


def calculate(operation, balance, purchase, already_returned):
    """Вернуть изменение баланса и причину отказа, если операция отклонена."""
    if operation["type"] == "purchase":
        if purchase is not None:
            return 0, "duplicate_purchase"
        return int(operation["amount"] * Decimal("0.05")), None

    if operation["type"] == "return":
        if purchase is None:
            return 0, "purchase_not_found"
        if purchase["customer_id"] != operation["customer_id"]:
            return 0, "customer_mismatch"
        if already_returned:
            return 0, "already_returned"
        # Возврат может увести счёт в минус.
        return -purchase["points_delta"], None

    points = operation["points"]
    if points > operation["amount"] * Decimal("0.30"):
        return 0, "limit_exceeded"
    if points > balance:
        return 0, "insufficient_balance"
    return -points, None
