"""Train the transaction-risk model and print cross-validated metrics.

Run:  python -m scripts.train_model
"""
import json

from amanah import monitoring as mon

if __name__ == "__main__":
    customers, tx = mon.load_data()
    X = mon.build_features(customers, tx)
    y = mon.labels(customers).reindex(X.index).fillna(0)
    model, metrics = mon.RiskModel.train(X, y)
    model.save()
    print(json.dumps(metrics, indent=2))
