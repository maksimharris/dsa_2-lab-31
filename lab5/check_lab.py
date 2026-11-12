import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

API = "http://localhost:8000"
NOTIFIER = "http://localhost:8001"
ANALYTICS = "http://localhost:8002"


def request(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=8) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def wait_for(url, condition):
    end = time.monotonic() + 40
    while time.monotonic() < end:
        code, body = request(url)
        if code == 200 and condition(body):
            return body
        time.sleep(0.2)
    raise AssertionError(f"Timed out waiting for {url}")


def main():
    tag = uuid4().hex[:8]
    customer, other, store = f"C-{tag}", f"Other-{tag}", f"S-{tag}"
    check = f"Receipt-{tag}"

    def submit(number, kind, reason, delta, balance, **changes):
        operation_id = f"{tag}-{number}"
        data = {
            "operation_id": operation_id,
            "type": kind,
            "customer_id": customer,
            "store_id": store,
            "check_number": check,
            "occurred_at": "2026-11-10T14:32:05+07:00",
            **changes,
        }
        assert request(f"{API}/operations", data) == (202, {"operation_id": operation_id})
        event = wait_for(f"{API}/operations/{operation_id}", lambda _: True)
        assert event["status"] == ("applied" if reason is None else "rejected"), event
        assert (event["reject_reason"], event["points_delta"], event["balance_after"]) == (
            reason, delta, balance,
        ), event
        print(f"{number:>2}. {kind:8} {reason or 'applied':22} delta={delta:4} balance={balance:4}")
        return data

    assert request(f"{API}/health")[0] == 200
    assert request(f"{API}/operations/missing-{tag}")[0] == 404
    assert request(f"{API}/accounts/{customer}")[0] == 404
    assert request(f"{ANALYTICS}/stores/{store}")[0] == 404

    purchase = submit(1, "purchase", None, 124, 124, amount="2490.00")
    assert request(f"{API}/operations", {**purchase, "amount": "0"})[0] == 422
    assert request(f"{API}/operations", {**purchase, "points": 1})[0] == 422
    submit(2, "purchase", "duplicate_purchase", 0, 124, amount="100")
    submit(3, "return", "purchase_not_found", 0, 124, check_number=f"Missing-{tag}")
    submit(4, "return", "customer_mismatch", 0, 0, customer_id=other)
    submit(5, "redeem", "limit_exceeded", 0, 124, amount="100", points=150)
    submit(6, "redeem", "insufficient_balance", 0, 124, amount="600", points=150)
    submit(7, "redeem", None, -50, 74, amount="200", points=50)
    submit(8, "return", None, -124, -50)
    submit(9, "return", "already_returned", 0, -50)

    assert request(f"{API}/operations", purchase)[0] == 202
    account = wait_for(f"{API}/accounts/{customer}", lambda body: len(body["operations"]) == 8)
    assert account["balance"] == -50
    assert [row["operation_id"] for row in account["operations"]] == [
        f"{tag}-{number}" for number in (9, 8, 7, 6, 5, 3, 2, 1)
    ]
    stats = wait_for(f"{ANALYTICS}/stores/{store}", lambda row: row["rejected"] == 6)
    assert stats == {
        "store_id": store, "purchases": 1, "returns": 1, "redeems": 1,
        "rejected": 6, "earned_points": 124, "returned_points": 124, "redeemed_points": 50,
    }, stats
    assert stats in request(f"{ANALYTICS}/stores")[1]
    notes = wait_for(f"{NOTIFIER}/notifications?customer_id={customer}", lambda rows: len(rows) == 8)
    assert notes[0]["text"] == "Начислено 124 баллов, баланс 124"
    assert notes[-1]["text"] == "Операция отклонена: already_returned"
    assert request(f"{NOTIFIER}/stats")[1]["sent_notifications"] >= 9
    assert request(f"{ANALYTICS}/stats")[1]["received_events"] >= 9
    print(f"OK. Customer: {customer}, store: {store}")


if __name__ == "__main__":
    main()
