from tests.conftest import upload


def test_upload_multiple_files_and_list(user_client):
    files = [("files", (n, open(f"../sample_data/{n}", "rb").read(), "text/csv"))
             for n in ("sales.csv", "customers.csv", "products.csv")]
    r = user_client.post("/api/datasets", files=files)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["errors"] == []
    names = {d["table_name"] for d in body["datasets"]}
    assert names == {"sales", "customers", "products"}
    sales = next(d for d in body["datasets"] if d["table_name"] == "sales")
    assert sales["row_count"] > 4000 and sales["columns"][1]["type"] == "datetime"
    assert "score" in sales["quality"]
    assert len(user_client.get("/api/datasets").json()) == 3


def test_partial_upload_reports_errors(user_client):
    files = [("files", ("good.csv", b"a,b\n1,2\n", "text/csv")), ("files", ("bad.csv", b"", "text/csv"))]
    r = user_client.post("/api/datasets", files=files)
    assert r.status_code == 201
    assert len(r.json()["datasets"]) == 1 and "bad.csv" in r.json()["errors"][0]


def test_all_invalid_upload_is_422(user_client):
    r = upload(user_client, "x.csv", b"\x00\x00binary")
    assert r.status_code == 422 and "binary" in r.json()["detail"]


def test_same_filename_gets_unique_table_name(user_client):
    upload(user_client, "sales.csv")
    r = upload(user_client, "sales.csv")
    assert r.json()["datasets"][0]["table_name"] == "sales_2"


def test_preview_and_delete(user_client, sales_dataset):
    ds_id = sales_dataset["id"]
    p = user_client.get(f"/api/datasets/{ds_id}/preview?limit=5").json()
    assert len(p["rows"]) == 5 and p["columns"][0] == "order_id"
    assert user_client.delete(f"/api/datasets/{ds_id}").status_code == 204
    assert user_client.get(f"/api/datasets/{ds_id}").status_code == 404


def test_direct_sql_and_csv_export(user_client, sales_dataset):
    body = {"sql": "SELECT region, round(sum(revenue)) AS rev FROM sales GROUP BY 1 ORDER BY 2 DESC",
            "dataset_ids": [sales_dataset["id"]]}
    r = user_client.post("/api/datasets/query", json=body)
    assert r.status_code == 200 and r.json()["columns"] == ["region", "rev"] and r.json()["row_count"] == 5
    again = user_client.post("/api/datasets/query", json=body).json()
    assert again["cached"] is True
    csv = user_client.post("/api/datasets/query.csv", json=body)
    assert csv.headers["content-type"].startswith("text/csv") and csv.text.startswith("region,rev")


def test_bad_sql_is_400_with_message(user_client, sales_dataset):
    r = user_client.post("/api/datasets/query", json={"sql": "SELECT nope FROM sales",
                                                      "dataset_ids": [sales_dataset["id"]]})
    assert r.status_code == 400 and "nope" in r.json()["detail"]


def test_data_is_encrypted_on_disk(user_client, tmp_path):
    from pathlib import Path

    from app.config import get_settings
    marker = b"VerySecretCustomerName"
    r = upload(user_client, "secret.csv", b"name,v\n" + marker + b",1\nOther,2\n")
    assert r.status_code == 201
    blobs = list(Path(get_settings().storage_dir).glob("*.bin"))
    assert blobs and all(marker not in b.read_bytes() for b in blobs)
