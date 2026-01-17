import argparse
from app.db import load_plates_db, upsert_plate, delete_plate


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add")
    a.add_argument("--plate", required=True)
    a.add_argument("--opis", required=True)
    a.add_argument("--tag", default="")

    d = sub.add_parser("del")
    d.add_argument("--plate", required=True)

    sub.add_parser("list")

    args = p.parse_args()

    if args.cmd == "add":
        upsert_plate(args.plate.upper().replace(" ", ""), args.opis, args.tag)
        print("OK")
    elif args.cmd == "del":
        ok = delete_plate(args.plate.upper().replace(" ", ""))
        print("OK" if ok else "NOT_FOUND")
    elif args.cmd == "list":
        db = load_plates_db()
        for k, v in db.items():
            print(k, v)


if __name__ == "__main__":
    main()
