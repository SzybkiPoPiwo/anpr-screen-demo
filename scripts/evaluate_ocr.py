import argparse
import csv
from pathlib import Path

import cv2
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

from app.ocr import PlateOcr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, help="folder z obrazami (np. samples/)")
    ap.add_argument("--labels", required=True, help="labels.csv: filename,plate")
    ap.add_argument("--no-pre", action="store_true", help="wyłącz preprocessing (wariant A)")
    args = ap.parse_args()

    images_dir = Path(args.images)
    labels_path = Path(args.labels)

    ocr = PlateOcr(use_preprocessing=not args.no_pre, gpu=False)

    y_true = []
    y_pred = []

    with labels_path.open("r", encoding="utf-8") as f:
        r = csv.reader(f)
        for row in r:
            if not row or len(row) < 2:
                continue
            fname = row[0].strip()
            plate = row[1].strip().upper().replace(" ", "")

            img_path = images_dir / fname
            img = cv2.imread(str(img_path))
            if img is None:
                print(f"WARNING: nie mogę wczytać {img_path}")
                continue

            res = ocr.read_plate(img)
            pred = (res.plate or "").upper().replace(" ", "")

            y_true.append(plate)
            y_pred.append(pred)

    if not y_true:
        print("Brak danych do ewaluacji.")
        return

    # “Exact match” -> binarna klasyfikacja: poprawnie/źle
    correct = [int(t == p) for t, p in zip(y_true, y_pred)]
    y_bin_true = [1] * len(correct)
    y_bin_pred = correct

    print("Samples:", len(correct))
    print("Accuracy:", accuracy_score(y_bin_true, y_bin_pred))
    print("Precision:", precision_score(y_bin_true, y_bin_pred, zero_division=0))
    print("Recall:", recall_score(y_bin_true, y_bin_pred, zero_division=0))
    print("F1:", f1_score(y_bin_true, y_bin_pred, zero_division=0))


if __name__ == "__main__":
    main()
