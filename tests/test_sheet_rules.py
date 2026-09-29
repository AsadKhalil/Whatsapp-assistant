from app.sheet_rules import sensitive_columns, tab_problems

HEADERS = ["Date", "Item", "Qty", "Name", "Phone"]


def test_contact_columns_are_flagged():
    assert sensitive_columns(["Item", "Customer Phone", "Email", "CNIC no", "Price"]) == [
        "Customer Phone", "Email", "CNIC no"]
    assert sensitive_columns(["Item", "Price"]) == []


def test_tab_problems_explain_each_guardrail():
    ok = {"customer": ["own", "append"], "owner_column": "Phone", "fill": {"Name": "name", "Phone": "phone"}}
    assert tab_problems("Orders", ok, HEADERS, confirmed=False) == []
    assert "pick which column" in tab_problems("Orders", {"customer": ["own"], "owner_column": ""}, HEADERS, False)[0]
    assert "'Mobile' is not in the tab" in tab_problems(
        "Orders", {"customer": ["append"], "fill": {"Mobile": "phone"}}, HEADERS, False)[0]
    assert "every customer would see Phone" in tab_problems("Orders", {"customer": ["read"]}, HEADERS, False)[0]
    assert tab_problems("Orders", {"customer": ["read"]}, HEADERS, confirmed=True) == []
