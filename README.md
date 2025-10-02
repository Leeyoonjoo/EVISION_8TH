# EVISION_8TH

## week1-------------------------------------------------
사일로 : 논문, 챕터 : Forensics 선택.

논문 리뷰 작성 - https://www.notion.so/In-Vehicle-network-instrusion-detection-using-deep-convolutional-neural-network-264b17db21db80f2ac6bf168b26f3f6e?source=copy_link 

## week2---------------------------------------------------
사일로 : 개발, 챕터 : Forensic 선택 

<프로젝트 안내>
주제 : 문서 파일 분석을 위한 REST API 서버 구축 

기능 
  1. 파일 해시값 계산 (MD5, SHA-256)
  2. 파일 시그니처 확인(매직 넘버로 실제 파일 타입 판별)
  3. 메타데이터 추출(생성/ 수정 시간 등)
  4. 문서 파일 내 특정 키워드 검색 

결과 : .CSV 형태의 파일과 JSON파일 (results 폴더 내에 있음)
<img width="1279" height="170" alt="image" src="https://github.com/user-attachments/assets/0500a4d8-4cd7-4d5c-aa50-57bba23fe85f" />


스크린샷 : 

<img width="503" height="157" alt="image" src="https://github.com/user-attachments/assets/c54ad0dd-5d74-4cf5-9cd0-07fa04c141af" />

<img width="476" height="245" alt="image" src="https://github.com/user-attachments/assets/424e5ba8-9038-4263-9abb-07819f5b2325" />



실행방법
```bash
python -m venv venv
venv\Scripts\activate   # Windows
source venv/bin/activate # macOS/Linux

pip install -r requirements.txt
python app1.py
```

cmd에서 API 사용
```bash
curl -X POST http://127.0.0.1:5000/analysis -F "files=@sample.docx" -F "keyword=<임의로 설정>"
```



