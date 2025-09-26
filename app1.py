import os, io, csv, uuid, zipfile, hashlib, datetime
from flask import Flask, request, jsonify, send_from_directory, url_for, abort
from werkzeug.utils import secure_filename                                              # 업로드된 파일 이름을 안전한 형태로 변환해주는 역할.

# 텍스트 추출 라이버러리 (설치 : pip install PyPDF2 python-docx)
import PyPDF2
from docx import Document

import zipfile
from io import BytesIO
from flask import send_file

# ----------------설정--------------------------
BASE_DIR = os.path.dirname(__file__)                                                    # 현재 실행 중인 app1.py 파일이 있는 디렉터리 경로를 가져온다.
UPLOAD_DIR = os.path.join(BASE_DIR,"uploads")                                           # uploads 라는 하위 폴더 경로를 생성한다. 이거는 업로드된 원본 파일을 저장할 위치이다.
RESULT_DIR = os.path.join(BASE_DIR,"results")                                           # 분석 결과(CSV/JSON)를 저장할 하위 폴더 경로 
os.makedirs(UPLOAD_DIR, exist_ok=True)                                                  # 해당 디렉ㅌ리가 없으면 자동 생성한다. exist_ok=True 옵션 덕분에 이미 있어도 에러가 나지 않는다. 
os.makedirs(RESULT_DIR, exist_ok=True)                                                  

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False                                                     # 한글을 \uxxxx 형식(유니코드 이스케이프)로 출력하지만, False로 설정하면 JSON응답에서 한글이 그대로 출력됨 
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024                                    # 최대 512MB 업로드

# -------------시그니처 테이블------------------
MAGIC_TABLE = [
    (b"\x89PNG\r\n\x1a\n","PNG"),   
    (b"\xFF\xD8\xFF", "JPEG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"%PDF-", "PDF"),
    (b"PK\x03\x04", "ZIP/OOXML"),  # zip, docx/xlsx/pptx 가능
    (b"\x25\x21\x50\x53", "PostScript"),
    (b"\x52\x61\x72\x21\x1A\x07\x00", "RAR"),
    (b"\x37\x7A\xBC\xAF\x27\x1C", "7Z"),
]

# --------------유틸 함수 ----------------
def detect_signature(path):                                                             # 파일의 시그니처를 확인하는 함수 
    with open(path,"rb") as f:                                                          # 파일을 바이너리(rb) 모드로 열고 
        head = f.read(16)                                                               # 처음 16바이트(헤더 부분)을 읽는다.
    for sig, label in MAGIC_TABLE:                                                      # MAGIC_TABLE에 있는 시그니처 패턴과 비교 
        if head.startswith(sig):                                                        # 파일 시작 부분이 해당 시그니처로 시작하면 
            if label == "ZIP/OOXML":                                                    # zip/OOXML인 경우 (docx/xLsx/pptx 구분 필요)
                try:
                    with zipfile.ZipFile(path) as z:
                        names = set(z.namelist())                                       # 압축 내부 파일 목록 추출 
                        if any(n.startwith("word/") for n in names):
                            return "DOCX (OOXML)"                                   
                        if any(n.startswith("xl/") for n in names):
                            return "XLSX (OOXML)"
                        if any(n.startswith("ppt/") for n in names):
                            return "PPTX (OOXML)"
                except Exception:
                    pass                                                                # zip 파일로 못 열면 그냥 기본 레이블 반환
            return label                                                                # 해당 포맷 이름 반환 
        return "Unknown"                                                                # 어떤 것도 매칭안되면 Unknown 반환 
    
def hash_file(path, algo="md5", chunk_size=1024*1024):                                  # 파일의 해시값(MD5, SHA-256 등)을 계산하는 함수
    h = hashlib.new(algo)                                                               # 헤시 객체 생성 
    with open(path,"rb") as f:                                                          # 파일을 바이너리 모드로 열기 
        for chunk in iter(lambda: f.read(chunk_size),b""): 
            h.update(chunk)                                                             # 파일 데이터를 조금씩 읽어서 해시에 추가 
        return h.hexdigest()                                                            # 최종 해시값(16진 문자열) 반환 
    
def get_metadata(path):                                                                             # 메타데이터(파일크기와 시간정보(수정/생성 시간 등)) 추출하는 함수 
    st = os.stat(path)                                                                              # 파일 상태 정보 가져오기 
    size=st.st_size                                                                                 # 파일 크기 (바이트 단위)
    mtime = datetime.datetime.fromtimestamp(st.st_mtime).isoformat(sep=" ",timespec="seconds")      # 타임스탬프를 사람이 읽을 수 있는 문자열로 변환 
    ctime = datetime.datetime.fromtimestamp(st.st_ctime).isoformat(sep=" ",timespec="seconds")
    
    return {"size_bytes":size, "modified":mtime, "created_or_changed":ctime}

# 문서 파일 안에서 텍스트를 추출하는 함수들 
def text_from_txt(path):                                                                            # 일반 텍스트 파일에서 문자열을 읽음 
    with open(path, "rb") as f:                                                                     # 바이너리 모드로 파일 열기 
        data = f.read()                                                                             # 전체 파일 내용을 바이트로 읽기 
    for enc in ("utf-8","cp949","euc-kr","latin-1"):
        try:
            return data.decode(enc)                                                                 # 순서대로 인코딩 시도 
        except Exception:
            continue
    return ""                                                                                       # 실패하면 빈 문자열 반환 
    
def text_from_pdf(path):                                                                            # PDF 파일 안에서 페이지별 텍스트 추출 
    text = []
    with open(path, "rb") as f:
        reader = PyPDF2.PdfReader(f)                                                                # PDF 리더 객체 생성
        for i in range(len(reader.pages)):
            try:
                text.append(reader.pages[i].extract_text() or "")
            except Exception:
                text.append("")
    return "\n".join(text)

def text_from_docx(path):
    doc = Document(path)                                                                            # python-docx 라이브러리로 열기
    return "\n".join(p.text for p in doc.paragraphs)

def keyword_search(path, signature_label, keyword):                                                 # 특정 키워드를 검색하는 함수 
    if not keyword:
        return False, 0, ""                                                                         # 키워드가 없으면 검색 안함 
    ext = os.path.splitext(path)[1].lower()
    content = ""
    try:
        if ext in [".txt",".csv",".log",".md"]:                                                     # 파일 확장자 /시그니처 기반 텍스트 추출 
            content = text_from_txt(path)
        elif signature_label.startswith("PDF") or ext ==".pdf":
            content = text_from_pdf(path)
        elif signature_label.startswith("DOCX") or ext ==".docx":
            content = text_from_docx(path)
    except Exception:
        content = ""                                                                                # 텍스트가 없으면 검색 중단 (pdf가 스캔 이미지라서 텍스트가 안 뽑히는 경우도 포함)
    
    
    if not content: 
        return False, 0, ""
    low_c, low_k = content.lower(), keyword.lower()
    count = low_c.count(low_k)                                                                      # 키워드 등장 횟수 세기
    if count == 0: 
        return False, 0, ""                                                                         # 없으면 False 반환 
    i = low_c.find(low_k)                                                                           # 첫 번째 매칭 위치 주변 텍스트 샘플 추출 (키워드 앞뒤 80자 잘라서 반환 - 이건 그냥 임의로 기능 추가한 것)
    sample = content[max(0, i-80): min(len(content), i+len(keyword)+80)].replace("\n", " ")
    return True, count, sample

# 분석 결과를 파일로 저장하는 기능 함수 - write_csv, save_json
def write_csv(analysis_id, rows):
    csv_name = f"{analysis_id}.csv"
    csv_path = os.path.join(RESULT_DIR, csv_name)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["filename","signature","md5","sha256","size_bytes","modified","created_or_changed",
                    "keyword","keyword_found","keyword_count","keyword_sample"])
        for r in rows:
            w.writerow([r["filename"], r["signature"], r["md5"], r["sha256"], r["size_bytes"],
                        r["modified"], r["created_or_changed"], r["keyword"], "Y" if r["keyword_found"] else "N",
                        r["keyword_count"], r["keyword_sample"]])
        
    return csv_name

def save_json(analysis_id, payload):
    import json
    json_path = os.path.join(RESULT_DIR, f"{analysis_id}.json")
    with open(json_path, "w",encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return json_path

#-------------엔드포인트-----------------
@app.route("/health", methods=["GET"])                                                              # 서버 상태 확인용 (GET /health) - 서버가 정상 동작하는지 확인하는 헬스 체크 API
def health():
    return jsonify({"status":"ok"}), 200                                                            # 응답 : {"status":"ok"} + HTTP 200 코드 

@app.route("/analysis", methods=["POST"])                                                           # 파일 분석 요청용 (POST /analyses)
def create_analysis():
    """                                                                                             # 요청 형식 정하기 
    multipart/form-data:
      - files: 여러 개 업로드 가능
      - keyword: (선택) 문자열
    """
    files = request.files.getlist("files")
    keyword = (request.form.get("keyword") or "").strip()

    if not files:                                                                                   # 파일이 없으면 400 Bad Request 반환 
        return jsonify({"error": "files 필드에 업로드할 파일을 추가하세요."}), 400

    analysis_id = uuid.uuid4().hex                                                                  # 분석 ID 생성 및 저장 폴더 만들기
    upload_subdir = os.path.join(UPLOAD_DIR, analysis_id)                                           # 각 요청마다 uuid 기반 고유한 analysis_id 생성, 업로드 파일 저장할 전용 폴더를 만듦
    os.makedirs(upload_subdir,exist_ok=True)                                                        
    
    results=[]
    for f in files:
        if not f or f.filename == "":
            continue
        fname = secure_filename(f.filename)                                                         # 위험한 문자를 제거해 안전한 파일명으로 저장 
        save_path = os.path.join(upload_subdir,fname)
        
        # 파일명 충돌 방지 - 같은 이름 파일이 이미 있으면 _1, _2 붙여 출돌 방지 
        base, ext = os.path.splitext(fname)
        i = 1
        while os.path.exists(save_path):
            fname = f"{base}_{i}{ext}"
            save_path = os.path.join(upload_subdir,fname)
            i += 1
        f.save(save_path)
        
        sig = detect_signature(save_path)                                                           # 시그니처 (매직 넘버 기반 포맷 판별)
        md5 = hash_file(save_path,"md5")                                                            # 해시(MD5, SHA-256)
        sha256 = hash_file(save_path,"sha256")                                                      
        meta = get_metadata(save_path)                                                              # 메타데이터 (파일 크기, 수정/생성 시간)
        found, count, sample = keyword_search(save_path,sig,keyword)                                # 키워드 검색 (발견 여부, 횟수, 문맥 샘플)
        
        results.append({                                                                            # 분석 결과 
            "filename" : fname,
            "signature" : sig,
            "md5": md5,
            "sha256": sha256,
            **meta,
            "keyword":keyword,
            "keyword_found": found,
            "keyword_count":count,
            "keyword_sample":sample
        })
    
    csv_name = write_csv(analysis_id, results)
    payload = {                                                                                     # JSON 페이로드 구성 
        "analysis_id": analysis_id,                                                                 # analysis_id : 분석 요청 고유 ID
        "created_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",               # 분석 시각
        "count": len(results),                                                                      # 처리한 파일 개수
        "results": results,                                                                         # 파일별 상세 분석 결과
        "links": {                                                                                  
            "self": url_for("get_analysis", analysis_id=analysis_id, _external=True),               # JSON 결과 다시 확인할 수 있는 API 주소
            "csv":  url_for("download_csv", analysis_id=analysis_id, _external=True),               # CSV 결과 다운로드 주소
        }
    }
    save_json(analysis_id, payload)
    return jsonify(payload), 201                                                                    # 클라이언트에 응답 - JSON 형태로 분석 결과 반환 

# 분석 결과 조회하는 API 엔드포인트 
# 사용자가 방금 업로드한 분석 결과를 다시 확인가능하다. 
# 파일이 많아서 분석에 시간이 걸리면, 클라이언트는 POST /analyses 후 받은 anaysis_id 만 저장했다가 나중에 GET /analyses/<id>로 결과를 확인가능 
@app.route("/analysis/<analysis_id>", methods=["GET"])                                              # 클라이언트가 GET /analysis.abcd1234 같은 요청을 보내면 실행된다. <analysis_id>는 동적 파라미터이며 요청 URL 안의 ID 값을 함수 인자로 전달받는다. 
def get_analysis(analysis_id):
    json_path = os.path.join(RESULT_DIR, f"{analysis_id}.json")                                     # results/abcd1234.json 같은 파일 경로를 만든다. 이 파일은 POST /analses 요청 시 미리 저장해 둔 결과 JSON이다. 
    if not os.path.exists(json_path):                                                               # 해당 ID로 된 결과 파일이 없으면 404 Not Found 반환 - 잘못된 ID나 오래된 결과 요청 시 에러 처리이다. 
        abort(404, description="Not Found")
    import json
    with open(json_path,"r",encoding="utf-8") as f:                                                 # UTF-8 로 JSON 파일 열어서 Python dict로 로드 
        data = json.load(f)
    return jsonify(data), 200                                                                       # JSON 응답 + HTTP 200 코드 반환. jsonify는 dict에서 JSON 문자열로 자동 변환해주고, MIME 타입도 application/json 으로 설정한다 

@app.route("/analysis/<analysis_id>/csv",methods=["GET"])                                            # REST API에서 CSV 결과 파일을 다운로드할 수 있게 해주는 엔드포인트
def download_csv(analysis_id):                                                                      # 사용자가 특정 분석 ID(=analysis_id)를 지정하면, 서버에 저장된 CSV 파일을 찾아서 그대로 내려주는 기능이다. 
    filename=f"{analysis_id}.csv"
    path = os.path.join(RESULT_DIR, filename)
    if not os.path.exists(path):
        abort(404,description="csv not Found")
    return send_from_directory(RESULT_DIR, filename,as_attachment=True)


# ------------ 실행 --------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)