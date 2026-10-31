# Supervisor-led Software Engineering Team

สั่งงานผ่าน **Supervisor Agent ตัวเดียว** หัวหน้าจะวางข้อกำหนด แบ่งงานให้ Frontend,
Backend และ QA แล้วตรวจรับผล ระบบใช้ **Codex CLI บนเครื่อง** เป็นค่าเริ่มต้น
และใช้ CrewAI Flow จัดลำดับงาน ไม่ต้องใช้ SWU API token

## เปิด Agent Office (แนะนำ)

Office เป็นหน้าเว็บบนเครื่องสำหรับคุยกับหัวหน้าในโปรเจกต์เดิม ดูทีมรับงาน
เปิดเว็บที่สร้าง และตรวจประวัติการแก้ไข โดยใช้ Codex ที่ล็อกอินไว้แล้ว

```sh
cd /Users/neutrino/Desktop/code/SW_BurntToCrisp/CPE320_BurntToCrisp
PYTHONPATH=src .venv/bin/python -m se_team.office
```

บน macOS ดับเบิลคลิก `start-office.command` ใน Finder เพื่อเปิดครั้งต่อไปได้ด้วย

เปิด [http://127.0.0.1:8787](http://127.0.0.1:8787) แล้วทำดังนี้:

1. สร้างโปรเจกต์ ตั้งชื่อและเล่าไอเดีย
2. ส่งคำสั่งในแชตหัวหน้า เช่น “เริ่มสร้างตามโจทย์นี้”
3. ดูสถานะจริงของทีมใน Agent office และเปิดผลลัพธ์ใน “เว็บของคุณ”
4. ส่งคำสั่งแก้ในแชตเดิม เช่น “เปลี่ยนสีและเพิ่มปุ่มบันทึก”
5. กด “ไฟล์เว็บ & บันทึกงาน” เพื่อเปิดโฟลเดอร์ ดูไฟล์ปัจจุบัน และสรุปงาน

คำสั่งที่ส่งระหว่างทีมทำงานจะเข้าคิวและทำตามลำดับ ปุ่มหยุดงานหยุดคำสั่งปัจจุบัน
และยกเลิกคำสั่งที่ยังรออยู่ บันทึกงานและไฟล์ปัจจุบันยังอยู่ ไฟล์ที่เขียนแล้วจะไม่ย้อนกลับอัตโนมัติ
หาก Codex แจ้งข้อจำกัดการใช้งาน Office จะพักคิว พร้อมปุ่มตรวจการเชื่อมต่ออีกครั้ง
การตรวจสถานะไม่เริ่มงานโมเดลและไม่ซื้อเครดิต เมื่อกลับมาใช้ได้ คิวที่เก็บไว้จึงทำต่อ
ถ้า Office ปิดกลางงาน คำสั่งนั้นจะถูกระบุว่าขัดจังหวะและสามารถส่งใหม่ได้
โปรแกรมประมวลผลทีละคำสั่ง ส่วนงาน Frontend/Backend ภายในคำสั่งเดียวกันทำพร้อมกันได้

สถานะและการเคลื่อนที่ของตัวละครอ้างอิงการเริ่ม/จบงาน Codex การเขียนไฟล์
และผล pytest จริง ไม่สุ่มงานเพื่อแสดงผล ไม่มีการเก็บข้อความเหตุผลภายในของโมเดล
หัวหน้าได้รับ spec ล่าสุด ไฟล์เดิม และบทสนทนาช่วงล่าสุดประกอบคำสั่งทุกครั้ง
ความต่อเนื่องมาจากข้อมูลโปรเจกต์ที่เก็บไว้ ไม่ได้อาศัยให้โปรเซสโมเดลเปิดค้างตลอดเวลา

ประวัติบันทึกถาวรที่ `workspace/office/office.sqlite3`
เว็บแต่ละโปรเจกต์อยู่ในโฟลเดอร์อ่านง่ายใกล้ราก เช่น `websites/BurningUpp/`
ทุกคำสั่งแก้ไฟล์ในโฟลเดอร์เดิม ไม่สร้างสำเนาเว็บหรือโฟลเดอร์รอบใหม่

```text
websites/BurningUpp/
├── frontend/       หน้าเว็บ
├── backend/        ระบบข้อมูล
├── tests/          ชุดทดสอบปัจจุบัน
├── data/           ข้อมูลที่ใช้จริง
└── preview.log     ข้อความจากการเปิดเว็บครั้งล่าสุด
```

Office เก็บแชต คำสั่ง รายชื่อไฟล์ที่เปลี่ยน จำนวนบรรทัด และผลตรวจแบบสั้น
ไม่เก็บโค้ดหรือผลทดสอบเต็มย้อนหลัง จึงเปิดหรือย้อนเว็บเวอร์ชันเก่าจาก log ไม่ได้
หากงานล้มเหลว ไฟล์ที่แก้ไปแล้วจะยังอยู่ในโฟลเดอร์หลัก ให้สั่งหัวหน้าทำต่อได้
Backend ใช้ `APP_DATA_DIR` ที่ชี้มายัง `data/` ส่วน QA ใช้ข้อมูลชั่วคราวแยกกัน
เมื่อเปิด Office ที่มีข้อมูลแบบเก่า ระบบจะย้ายเว็บล่าสุดกับข้อมูลเดิม
ตรวจว่าไฟล์ตรงกัน แล้วลบสำเนาเว็บเก่า พร้อมย่อบันทึกเดิมให้สั้นลง

เว็บพรีวิวรันในอีกโปรเซสบนอีกพอร์ตหนึ่ง ป้องกันการใช้ origin เดียวกับ Office
เปิดพรีวิวได้ครั้งละหนึ่งโปรเจกต์ และพักพรีวิวขณะทีมแก้ไฟล์
Office เปิดรับเฉพาะ localhost มีการตรวจ origin และ token สำหรับคำสั่งเปลี่ยนแปลงข้อมูล
ยังไม่มีระบบผู้ใช้หลายคนสำหรับ Office หรือการเผยแพร่ Office ขึ้นอินเทอร์เน็ต

ตัวเลือก: `--port 8788`, `--workspace <folder>`, `--max-rounds 2`
เก็บหน้าต่างที่รัน Office ไว้ระหว่างทีมทำงาน ใช้ Ctrl+C เพื่อปิด
สั่ง Office ใหม่ด้วยคำสั่งเดิมเมื่อกลับมาใช้งาน ประวัติจะยังอยู่

## การทำงาน

```mermaid
flowchart TD
    User[ผู้ใช้ส่ง brief] --> Supervisor[Supervisor วาง spec และออกคำสั่งงาน]
    Supervisor --> Plan[build_batches กำหนดลำดับหรือทำพร้อมกัน]
    Plan --> Frontend[Frontend / UX]
    Plan --> Backend[Backend / Data / Security]
    Frontend --> QA[QA ออกแบบ tests]
    Backend --> QA
    QA --> Runner[โปรแกรมรัน pytest จริง]
    Runner --> Review[Supervisor ตรวจหลักฐาน]
    Review -->|ผ่านและอนุมัติ| Delivery[ส่งมอบ]
    Review -->|พบข้อผิดพลาด| Fix[สั่งแก้เฉพาะผู้รับผิดชอบ]
    Fix --> QA
```

- หัวหน้าสร้าง `SpecPackage`: ขอบเขต, acceptance criteria, schema, API contract,
  คำสั่งงานเฉพาะบทบาท และ `build_batches`
- แต่ละ batch ทำตามลำดับ; Agent ภายใน batch ทำพร้อมกันได้ หัวหน้าอาจสั่ง Backend
  ก่อน Frontend หรือให้ทำพร้อมกันจาก contract ที่ตกลงแล้ว
- Agent ลูกน้องส่งไฟล์ที่เสนอให้โปรแกรมตรวจตำแหน่งและเขียนลงโฟลเดอร์ที่รับผิดชอบ
  Frontend เขียน `frontend/`, Backend เขียน `backend/`, QA เขียน `tests/`
- QA ออกแบบ tests จากข้อกำหนด โปรแกรมรัน pytest และอ่านจำนวนผลจาก JUnit XML
  คำตอบของโมเดลเปลี่ยนผลล้มเหลวให้เป็นผ่านไม่ได้
- หัวหน้าสั่งแก้ตามเจ้าของ bug แล้วทดสอบซ้ำได้ไม่เกิน `MAX_ROUNDS`
- การทดสอบผ่านและหัวหน้าอนุมัติจึงเป็น `SUCCESS`; ถ้าไม่อนุมัติจะเป็น
  `SIGNOFF_REJECTED` พร้อมเหตุผล

ทิศทางผลิตภัณฑ์จากคลิปอาจารย์และส่วนที่เป็นข้อเสนอการออกแบบเพิ่มเติมอยู่ใน
[docs/advisor-direction.md](docs/advisor-direction.md)

## Codex บนเครื่องหมายถึงอะไร

โปรแกรมนี้เรียก `codex exec` เป็นโปรเซสในเครื่อง และใช้สถานะล็อกอินที่ Codex CLI
จัดการเอง รองรับการล็อกอิน ChatGPT หรือ API key ตามบัญชีที่ใช้งาน
ไม่อ่านหรือคัดลอก token จากไฟล์ล็อกอินมาไว้ในโปรเจกต์

**ตัวโปรแกรมและไฟล์อยู่บนเครื่อง แต่โมเดล OpenAI ยังประมวลผลผ่านอินเทอร์เน็ต**
brief และ source ที่ส่งให้แต่ละ Agent จะถูกส่งให้บริการโมเดล จึงไม่ใช่โหมดออฟไลน์
และยังมีโควตา/ข้อจำกัดตามบัญชีหรือวิธีชำระค่าบริการของ Codex

ถ้าจะทำ UI ที่คุยกับ Agent ต่อเนื่องหรือแสดงสถานะแบบ streaming ภายหลัง
ใช้ Codex App Server ผ่าน JSON-RPC บน `stdio` ได้ เป็นคนละโปรโตคอลกับ
OpenAI-compatible HTTP `/v1/chat/completions`; ไม่สามารถเปลี่ยนแค่ SWU_BASE_URL
ให้เป็น localhost แล้วใช้ได้เลย สำหรับงานเป็นขั้นตอนในโปรเจกต์ Python นี้
`codex exec` เป็นส่วนเชื่อมต่อที่ใช้อยู่จริง

เอกสารทางการ:
[Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode),
[Authentication](https://learn.chatgpt.com/docs/auth),
[Codex App Server](https://learn.chatgpt.com/docs/app-server)

## เริ่มใช้งาน (macOS / Linux)

ต้องมี Python ที่รองรับ dependencies ใน `requirements.txt` และ Codex CLI

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
codex login
codex login status
```

ถ้ามี `.env` อยู่แล้วไม่ต้องเขียนทับ เพิ่ม `AGENT_BACKEND=codex` ได้
ถ้ายังไม่มี ให้คัดลอก `.env.example` เป็น `.env`

```ini
AGENT_BACKEND=codex
CODEX_BIN=codex
CODEX_MODEL=
ORCHESTRATOR_CODEX_MODEL=
FRONTEND_CODEX_MODEL=
BACKEND_CODEX_MODEL=
QA_CODEX_MODEL=
CODEX_TIMEOUT_SECONDS=600
MAX_ROUNDS=3
```

ปล่อย model ว่างเพื่อใช้ค่าเริ่มต้นของ Codex CLI หรือระบุ ID ที่บัญชีมีสิทธิ์ใช้
ค่ารายบทบาทมีลำดับความสำคัญเหนือ `CODEX_MODEL` และแยกจากตัวแปรโมเดลของ API เดิม
โปรแกรมไม่โหลด user config/plugins ของ Codex สำหรับ Agent jobs แต่ใช้ล็อกอินเดิม
ถ้า shell หา Codex ไม่พบ ให้ตั้ง `CODEX_BIN` เป็น path ของตัวโปรแกรม

```sh
PYTHONPATH=src .venv/bin/python -m se_team.main
```

หรือส่ง brief ให้หัวหน้าด้วยตัวเอง:

```sh
PYTHONPATH=src .venv/bin/python -m se_team.main \
  --brief "สร้างแพลตฟอร์ม BurningUpp ให้หลายองค์กรสมัครใช้ มีหลายทีม เช็กอินรายวัน ประเมินตามกติกาที่ระบุ และติดตามผลโดยหัวหน้าทีม" \
  --max-rounds 3
```

Windows PowerShell: ใช้ `$env:PYTHONPATH="src"` แล้วเรียก
`.\.venv\Scripts\python.exe -m se_team.main` พร้อมตัวเลือกเดียวกัน

เฉพาะโหมด CLI แบบครั้งเดียวด้านล่างยังแยกรอบที่ `workspace/runs/<run_id>/round_N/`
ส่วน Office ด้านบนใช้โฟลเดอร์ `websites/<ชื่อโปรเจกต์>/` อันเดิม:

```text
frontend/       ไฟล์ UI
backend/        FastAPI + SQLite source
tests/          ชุดทดสอบจาก QA
artifacts/      spec, work orders, handoff summaries และ QA evidence
```

ไฟล์ `agents.yaml` และ `tasks.yaml` อยู่ใน `src/se_team/crew/`
`codex_runtime.py` แปลงบทบาท/คำสั่งงานเป็น Codex jobs; `flow.py` ส่งงานตามแผนหัวหน้า
โปรแกรมจะไม่สร้างหรือ publish เว็บจริงจนกว่าจะสั่งรันงาน

## ตรวจสอบ

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q tests
```

ชุดทดสอบครอบคลุมการเลือก Codex แทน SWU, ขอบเขตไฟล์ของแต่ละบทบาท,
ผลทดสอบจริงที่หักล้างคำอ้างของโมเดล, แผนงานตามลำดับ, การแก้เฉพาะเจ้าของ bug,
การส่งต่อข้อผิดพลาด และการไม่อนุมัติส่งมอบ
ไม่เรียกโมเดลจริงใน unit tests; การทดสอบเชื่อมต่อบัญชีทำแยกต่างหาก

Codex jobs ใช้ read-only sandbox และส่งไฟล์กลับให้โปรแกรมเขียน
การจำกัด path ของโปรแกรมป้องกันการเขียนนอก workspace ผ่าน file handoff
แต่ pytest ยังเป็นการรัน Python บนเครื่อง ไม่ใช่ container สำหรับรันโค้ดที่ไม่ไว้ใจ

ตัวเชื่อม API เดิมยังเลือกได้ด้วย `AGENT_BACKEND=legacy` เพื่อความเข้ากันได้
ค่าเริ่มต้น `codex` ไม่เลือก SWU แม้ `.env` เดิมยังมี SWU_API_KEY อยู่
