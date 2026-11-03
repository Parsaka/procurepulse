"""RQ3 + RQ4 - What drives rework, and can we see it coming at PO creation?

Label: the PO item runs into a rework deviation (price change after invoice, quantity
change after goods receipt, variance payment block, reversal) within 90 days of creation.
Only the mature cohort is used, so every label is fully observed.

Features: only facts known when the PO item is created (category, spend taxonomy,
value, document type, company, whether a requisition exists, whether the vendor already
sent an invoice, PO size, creator type) plus point-in-time history of the vendor, the
creator and the material group: their smoothed rework rate over the training window.
Inside training this encoding is computed out-of-fold with folds grouped by purchase
order, so an item never sees its own label or those of its sibling items; the test
window uses the encoding fitted on the whole training window, which is exactly what
would be known on the day of deployment.

Validation is strictly temporal with a gap that mimics deployment: train on items created
2018-01-01..2018-05-02 (their 90-day labels are known by 2018-07-31), score items created
from 2018-08-01. Baselines: category prevalence and a logistic regression.
"""
from __future__ import annotations

import json

import lightgbm as lgb
import numpy as np
import pandas as pd
import shap
from sklearn.model_selection import GroupKFold
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder

from analytics.common import OUT_DIR, SEED, connect, publish, save_json

HORIZON_DAYS = 90
TRAIN_END = "2018-05-03"   # exclusive
TEST_START = "2018-08-01"
CATEGORICAL = ["item_category", "item_type", "document_type", "company_code", "spend_area",
               "sub_spend_area", "spend_classification"]
NUMERIC = ["log_value", "has_requisition", "invoice_before_po", "items_in_po", "creator_is_batch"]
HISTORY_KEYS = ["vendor_id", "created_by", "material_group"]
PRIOR_WEIGHT = 20.0

QUERY = f"""
with first_rework as (
    select e.case_key,
           min(case
                 when e.activity in ('Cancel Goods Receipt', 'Cancel Invoice Receipt', 'Cancel Subsequent Invoice') then e.event_at
                 when e.activity in ('Set Payment Block', 'Remove Payment Block') and p.dev_payment_block then e.event_at
                 when e.activity = 'Change Price' and e.event_at > p.first_ir_at then e.event_at
                 when e.activity = 'Change Quantity' and e.event_at > p.first_gr_at then e.event_at
               end) as first_rework_at
    from marts.fct_event e
    join marts.fct_po_item p using (case_key)
    where p.is_mature_cohort
    group by e.case_key
), po_size as (
    select purchase_order_id, count(*) as items_in_po from marts.fct_po_item group by 1
)
select p.case_key, p.purchase_order_id, p.po_created_at, p.item_category, p.item_category_code as item_type, p.document_type,
       p.company_code, coalesce(p.spend_area, 'Unknown') as spend_area,
       coalesce(p.sub_spend_area, 'Unknown') as sub_spend_area,
       coalesce(p.spend_classification, 'Unknown') as spend_classification,
       p.material_group, p.vendor_id, coalesce(p.created_by, 'NONE') as created_by,
       ln(1 + greatest(p.net_value_eur, 0)) as log_value, p.net_value_eur,
       cast(p.pr_created_at is not null and p.pr_created_at <= p.po_created_at as int) as has_requisition,
       cast(p.dev_po_after_invoice as int) as invoice_before_po,
       s.items_in_po,
       cast(coalesce(p.created_by, '') like 'BATCH%' as int) as creator_is_batch,
       extract(hour from p.po_created_at) as created_hour,
       extract(dayofweek from p.po_created_at) as created_weekday,
       cast(f.first_rework_at is not null
            and f.first_rework_at <= p.po_created_at + interval {HORIZON_DAYS} day as int) as label
from marts.fct_po_item p
join first_rework f using (case_key)
join po_size s using (purchase_order_id)
where p.is_mature_cohort
order by p.po_created_at, p.case_key
"""


def target_encode(train: pd.DataFrame, test: pd.DataFrame, key: str):
    """Smoothed label rate and item count per level of `key` (see module docstring)."""
    prior = train["label"].mean()

    def enc(fit_df, apply_df):
        g = fit_df.groupby(key)["label"].agg(["sum", "count"])
        rate = (g["sum"] + prior * PRIOR_WEIGHT) / (g["count"] + PRIOR_WEIGHT)
        return apply_df[key].map(rate).fillna(prior).to_numpy(), apply_df[key].map(g["count"]).fillna(0).to_numpy()

    oof_rate, oof_cnt = np.zeros(len(train)), np.zeros(len(train))
    for tr, va in GroupKFold(5).split(train, groups=train["purchase_order_id"]):
        oof_rate[va], oof_cnt[va] = enc(train.iloc[tr], train.iloc[va])
    # counts in OOF folds see 4/5 of the data; rescale so train and test are comparable
    oof_cnt = oof_cnt * 5 / 4
    test_rate, test_cnt = enc(train, test)
    return (oof_rate, oof_cnt), (test_rate, test_cnt)


def top_k_metrics(y, p, k=0.10):
    n = max(1, int(len(p) * k))
    idx = np.argsort(-p)[:n]
    precision = y[idx].mean()
    return {"precision_at_10pct": float(precision), "recall_at_10pct": float(y[idx].sum() / max(1, y.sum())),
            "lift_at_10pct": float(precision / y.mean())}


def evaluate(name, y, p):
    return {"model": name, "pr_auc": float(average_precision_score(y, p)), "roc_auc": float(roc_auc_score(y, p)),
            "brier": float(brier_score_loss(y, p)), **top_k_metrics(y, p)}


def main() -> None:
    con = connect()
    df = con.execute(QUERY).fetchdf()
    train = df[df.po_created_at < TRAIN_END].reset_index(drop=True)
    test = df[df.po_created_at >= TEST_START].reset_index(drop=True)
    hist_feats = []
    for key in HISTORY_KEYS:
        (tr_rate, tr_cnt), (te_rate, te_cnt) = target_encode(train, test, key)
        train[f"hist_rate_{key}"], test[f"hist_rate_{key}"] = tr_rate, te_rate
        train[f"hist_items_{key}"], test[f"hist_items_{key}"] = tr_cnt, te_cnt
        hist_feats += [f"hist_rate_{key}", f"hist_items_{key}"]
    for c in CATEGORICAL:
        known = sorted(train[c].astype(str).unique())
        cats = pd.CategoricalDtype(known + ["(unseen)"])
        train[c] = train[c].astype(str).astype(cats)
        test[c] = test[c].astype(str).where(test[c].astype(str).isin(known), "(unseen)").astype(cats)
    features = CATEGORICAL + NUMERIC + hist_feats
    y_tr, y_te = train["label"].to_numpy(), test["label"].to_numpy()

    results = []
    # Baseline 1: prevalence of the item category in training
    prev = train.groupby("item_category", observed=True)["label"].mean()
    results.append(evaluate("Baseline: category prevalence", y_te,
                            test["item_category"].map(prev).astype(float).fillna(y_tr.mean()).to_numpy()))
    # Baseline 2: logistic regression on categorical + numeric features (no history)
    logit = make_pipeline(OneHotEncoder(handle_unknown="ignore", min_frequency=20),
                          LogisticRegression(max_iter=2000, C=0.5))
    simple = CATEGORICAL + ["has_requisition", "invoice_before_po", "creator_is_batch"]
    logit.fit(train[simple].astype(str), y_tr)
    results.append(evaluate("Baseline: logistic regression", y_te, logit.predict_proba(test[simple].astype(str))[:, 1]))

    # Main model
    # Early stopping on the last month of the training window (temporal validation)
    params = dict(objective="binary", learning_rate=0.03, num_leaves=15, min_child_samples=300,
                  feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0,
                  cat_smooth=50, min_data_per_group=200, n_estimators=2000, random_state=SEED, verbose=-1)
    val_mask = train.po_created_at >= pd.Timestamp(TRAIN_END) - pd.Timedelta(days=30)
    model = lgb.LGBMClassifier(**params)
    model.fit(train.loc[~val_mask, features], y_tr[~val_mask], categorical_feature=CATEGORICAL,
              eval_set=[(train.loc[val_mask, features], y_tr[val_mask])], eval_metric="average_precision",
              callbacks=[lgb.early_stopping(100, verbose=False)])
    best_iter = model.best_iteration_
    # refit on the full training window with the chosen number of trees
    model = lgb.LGBMClassifier(**{**params, "n_estimators": best_iter})
    model.fit(train[features], y_tr, categorical_feature=CATEGORICAL)
    p_te = model.predict_proba(test[features])[:, 1]
    results.append(evaluate("LightGBM early warning", y_te, p_te))
    metrics = pd.DataFrame(results)
    publish(con, "model_metrics", metrics)

    # Calibration table (deciles of predicted risk)
    test["risk_score"] = p_te
    test["risk_decile"] = pd.qcut(test["risk_score"].rank(method="first"), 10, labels=False) + 1
    calib = (test.groupby("risk_decile").agg(items=("label", "size"), predicted=("risk_score", "mean"),
                                              observed=("label", "mean")).reset_index())
    publish(con, "model_calibration", calib)

    # Drivers (RQ3): mean |SHAP| on a test sample, grouped back to the business feature
    sample = test.sample(min(8000, len(test)), random_state=SEED)
    sv = shap.TreeExplainer(model).shap_values(sample[features])
    sv = sv[1] if isinstance(sv, list) else sv
    imp = pd.DataFrame({"feature": features, "mean_abs_shap": np.abs(sv).mean(axis=0)})
    imp["share"] = imp["mean_abs_shap"] / imp["mean_abs_shap"].sum()
    imp = imp.sort_values("mean_abs_shap", ascending=False)
    publish(con, "risk_drivers", imp)

    # Top reason per scored item (largest positive SHAP contribution) for the alert list
    full_sv = shap.TreeExplainer(model).shap_values(test[features])
    full_sv = full_sv[1] if isinstance(full_sv, list) else full_sv
    test["top_reason"] = np.array(features)[np.argmax(full_sv, axis=1)]
    alerts = test.loc[test["risk_decile"] == 10, ["case_key", "po_created_at", "item_category", "vendor_id",
                                                  "spend_area", "net_value_eur", "risk_score", "top_reason", "label"]]
    publish(con, "early_warning_scores", test[["case_key", "po_created_at", "risk_score", "risk_decile",
                                               "top_reason", "label"]])
    publish(con, "early_warning_alerts", alerts.sort_values("risk_score", ascending=False))

    # Concentration (RQ3): how much of the rework comes from few vendors?
    vend = df.groupby("vendor_id")["label"].sum().sort_values(ascending=False)
    top_n = max(1, int(round(len(vend) * 0.05)))
    concentration = {"vendors": int(len(vend)), "top5pct_vendors": top_n,
                     "top5pct_share_of_rework_items": float(vend.head(top_n).sum() / vend.sum())}

    model.booster_.save_model(str(OUT_DIR / "early_warning_lgbm.txt"))
    summary = {
        "horizon_days": HORIZON_DAYS, "trees": int(best_iter), "train_items": int(len(train)), "test_items": int(len(test)),
        "train_positive_rate": float(y_tr.mean()), "test_positive_rate": float(y_te.mean()),
        "train_window": ["2018-01-01", TRAIN_END], "test_window_start": TEST_START,
        "metrics": results, "concentration": concentration,
        "top_drivers": imp.head(8)[["feature", "share"]].to_dict("records"),
    }
    save_json("early_warning", summary)
    print(metrics.round(3).to_string(index=False))
    print(imp.head(10).round(3).to_string(index=False))
    print(json.dumps(concentration))
    print(calib.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
