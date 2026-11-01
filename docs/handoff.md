# ส่งต่องานให้เพื่อน — branch test

ชุดนี้มีทั้ง Agent Office และซอร์ส BurningUpp ปัจจุบัน โดยไม่รวมบัญชี ข้อมูลผู้ใช้
ฐานข้อมูล แชตเดิม หรือ credentials ของผู้พัฒนา เริ่มทำต่อได้จากไฟล์เดิมโดยไม่ต้องสร้างเว็บใหม่

## เริ่มบนเครื่องใหม่

ติดตั้ง Python 3.12 และ uv ตาม [เอกสาร uv](https://docs.astral.sh/uv/getting-started/installation/)
Node.js 22 ใช้สำหรับตรวจ syntax JavaScript ไม่ต้องติดตั้ง npm packages

```sh
git clone --branch test https://github.com/DelMiiYa/CPE320_BurntToCrisp.git
cd CPE320_BurntToCrisp
uv sync --locked
cp .env.example .env
uv run --locked se-office --import-website websites/BurningUpp
```

Windows PowerShell ใช้ `Copy-Item .env.example .env` แทน `cp` ได้
หากมี `.env` อยู่แล้วให้ใช้ไฟล์เดิม ไม่เขียนทับ credentials ของตัวเอง
เปิด http://127.0.0.1:8787 เลือก BurningUpp แล้วกด “เว็บของคุณ → เปิดเว็บหลัก”
การนำเข้าเพียงลงทะเบียนโฟลเดอร์และข้อกำหนดเดิม ไม่เรียกโมเดล ไม่คัดลอกเว็บ
รันคำสั่งเปิดเดิมอีกครั้งได้โดยไม่ทำข้อมูลหรือประวัติในเครื่องนั้นหาย

หากต้องการแก้เว็บเองโดยไม่ใช้ Agent:

```sh
uv run --locked python -m se_team.office.preview --source websites/BurningUpp --port 8788
```

เปิด http://127.0.0.1:8788 แล้วสมัครองค์กรและบัญชีใหม่ ข้อมูลเก็บใน
`websites/BurningUpp/data/` และถูกกันออกจาก Git

## ก่อนสั่งงาน Agent

ติดตั้ง [Antigravity CLI](https://antigravity.google/download) เปิด `agy` แล้วล็อกอินบัญชีของตัวเอง
ตรวจการเชื่อมต่อด้วย `agy models` จากนั้นส่งคำสั่งใน Office ได้
เครดิตและโควตาเป็นของบัญชีนั้น ไม่ได้แชร์มากับ Git
หากเลือก Codex ให้ตั้ง `AGENT_BACKEND=codex` และล็อกอิน Codex CLI ของตัวเอง

ตัวโปรแกรมอยู่บนเครื่อง แต่เมื่อส่งงานให้ Agent คำสั่งและซอร์สที่เกี่ยวข้องจะถูกส่ง
ไปยังบริการโมเดลของผู้ให้บริการ ห้ามใส่ secrets หรือข้อมูลผู้ใช้จริงในคำสั่งหรือซอร์ส
การเปิดเว็บและรันชุดทดสอบไม่จำเป็นต้องเรียกโมเดล

## ตำแหน่งที่แก้ต่อ

| ส่วนงาน | ตำแหน่ง |
| --- | --- |
| หน้าจอ Office | `src/se_team/office/static/` |
| คิวงานและการแบ่งงาน | `src/se_team/office/manager.py` |
| ตัวเชื่อมผู้ให้บริการ | `src/se_team/crew/antigravity_runtime.py`, `codex_runtime.py`, `runtime.py` |
| แผนแก้เฉพาะจุด/บริบท/แก้ไฟล์ | `src/se_team/crew/steps.py`, `performance.py` |
| บทบาทและงาน Agent | `src/se_team/crew/agents.yaml`, `tasks.yaml` |
| หน้าเว็บ BurningUpp | `websites/BurningUpp/frontend/` |
| API, สิทธิ์, SQLite | `websites/BurningUpp/backend/` |
| ชุดทดสอบเว็บไซต์ | `websites/BurningUpp/tests/` |
| ข้อกำหนดส่งต่อเว็บ | `websites/BurningUpp/project-spec.json` |

`project-spec.json` เก็บขอบเขตและ API contract ไม่ใช่ผลยืนยันว่าทำครบทุกข้อแล้ว
สถานะและงานค้างอยู่ใน [README ของเว็บไซต์](../websites/BurningUpp/README.md)
โดยเฉพาะตัวเลือกเดือนแบบ GUI, dropdown/UI และการตรวจการใช้งานบน browser เพิ่มเติม

## ตรวจงานก่อนส่งต่อ

```sh
uv run --locked python scripts/check_package.py
uv run --locked python scripts/check.py --all
node --check src/se_team/office/static/app.js
node --check websites/BurningUpp/frontend/app.js
```

ชุดทดสอบใช้ข้อมูลชั่วคราวแยกจากเว็บที่เปิดอยู่ และไม่เรียกโมเดลจริง
GitHub Actions ใช้ lockfile และรันชุดตรวจเดียวกันบน Python 3.12
ชุดทดสอบเว็บมีเพดาน 300 วินาทีสำหรับเครื่อง CI ที่ทำ password hashing ช้ากว่า
ปรับเฉพาะการตรวจนี้ด้วย `--website-timeout` ได้ โดยไม่เปลี่ยน timeout ของ Agent
ห้ามรัน pytest กวาดทั้ง repository โดยไม่แยกโฟลเดอร์ ให้ใช้ helper ข้างบน
เพื่อเลี่ยงชื่อ package `backend`/`tests` ของหลายโปรเจกต์ชนกัน

ก่อน commit ตรวจ `git status` ให้ไม่มี `.env`, `data/`, `workspace/`, ฐานข้อมูล,
`preview.log` หรือ `.office-layout.json` ติดไป อย่าใช้ `git add -f` กับไฟล์เหล่านี้
หากแก้ข้อกำหนดหรือ API ให้ทบทวน `project-spec.json` และเอกสารร่วมกับซอร์สด้วย
ประวัติ Office และ spec ที่แก้บนเครื่องไม่ซิงก์ข้ามเครื่องอัตโนมัติ

ใช้ branch `test` สำหรับชุดส่งต่องานนี้ การ push ไม่ควรเปลี่ยน `main`
ไม่มีขั้นตอน deploy หรือ merge อัตโนมัติใน workflow ที่เพิ่มให้
