#!/bin/zsh
# Double-click this file in Finder to start the local Office.
set -eu
PROJECT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$PROJECT_DIR"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  print 'ยังไม่มี Python environment ของโปรเจกต์ กรุณาติดตั้งตาม README ก่อนครับ'
  read -k 1 '?กดปุ่มใดก็ได้เพื่อปิด'
  exit 1
fi
print 'เปิด Office ที่ http://127.0.0.1:8787'
print 'เก็บหน้าต่างนี้ไว้ระหว่างทีมทำงาน ใช้ Control+C เพื่อปิด'
OFFICE_ARGS=(--port 8787)
if [[ -f "$PROJECT_DIR/websites/BurningUpp/project-spec.json" ]]; then
  OFFICE_ARGS+=(--import-website "$PROJECT_DIR/websites/BurningUpp")
fi
exec env PYTHONPATH="$PROJECT_DIR/src" "$PYTHON_BIN" -m se_team.office "${OFFICE_ARGS[@]}"
