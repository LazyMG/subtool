# subtool

영어 음성 영상의 자막을 **완전 로컬**에서 만들고 다듬는 도구입니다.

영상 → 영어 자막 받아쓰기(Whisper) → 플레이어 위에서 싱크 조정 → 읽기용 텍스트 추출

- 영상은 업로드하지 않고 원래 위치에서 바로 읽습니다. 외부 API 호출은 없습니다.
- 모든 처리는 CLI 명령 하나로 되어 있고, 웹 화면은 그 명령을 만들어 실행합니다.
- macOS(Apple Silicon)는 `mlx-whisper`, Windows·Linux·Intel Mac은 `faster-whisper`를 씁니다.

## 설치

공통: Python 3.10 이상, ffmpeg(ffprobe 포함)가 PATH에 있어야 합니다.

### macOS (Apple Silicon)
```bash
brew install ffmpeg
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-mac.txt
```

### Windows
```powershell
# ffmpeg: https://www.gyan.dev/ffmpeg/builds/ 등에서 받아 PATH에 추가
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```
NVIDIA GPU가 있어도 CUDA 라이브러리(cuBLAS·cuDNN)가 없으면 자동으로 CPU로 돌아갑니다.

### 선택: 자동 싱크 맞춤
```bash
pip install ffsubsync
```

첫 받아쓰기 때 모델을 내려받습니다 (large-v3-turbo 약 1.5GB).

## 웹 화면
```bash
python app.py            # 브라우저가 http://localhost:8000 으로 열림
python app.py --port 9000 --no-browser
```
- **왼쪽**: 영상 목록과 상태(새 영상 / 생성 중 % / 생성됨 / 싱크 완료 / 텍스트 추출됨), 작업 목록
- **가운데**: 통계 카드, 플레이어와 자막 오버레이, 싱크·저장·내보내기 / **받아쓰기** 탭(명령어 생성기)
- **오른쪽**: 선택한 자막 편집, 자막 목록 (겹침은 빨간 시각으로 표시)
- 받아쓰기·자동 맞춤은 백그라운드에서 돌고, 브라우저를 닫아도 서버가 켜져 있으면 계속됩니다. macOS는 끝나면 알림 센터로 알려 줍니다.
- 30초마다 자동 저장본을 남기고, 다시 열 때 복구할지 묻습니다.

### 단축키 (편집 탭, 한글 입력 상태에서도 동작)
| 키 | 동작 |
|---|---|
| `Space` | 재생 / 정지 |
| `←` `→` | 1초 이동 |
| `↑` `↓` | 이전 / 다음 자막 |
| `[` / `]` | 현재 자막 시작 / 끝 = 지금 재생 위치 |
| `,` / `.` | 현재 자막 ±0.1초 |
| `Shift` + `,` / `.` | 전체 자막 ±0.1초 |
| `S` | 지금 위치에서 자막 나누기 |
| `M` | 다음 자막과 합치기 |
| `I` / `O` | 받아쓰기 구간 시작 / 끝 → "받아쓰기로" 버튼으로 명령어 생성기에 넣기 |
| `Ctrl/Cmd` + `Z` / `Shift+Z` | 되돌리기 / 다시 실행 |
| `Ctrl/Cmd` + `S` | 저장 |

영상 위 자막을 클릭하면 그 자리에서 고칠 수 있습니다 (`Enter` 확정, `Esc` 취소, `Shift+Enter` 줄바꿈).

## CLI
```bash
python -m subtool transcribe 영상.mp4
python -m subtool transcribe 영상.mp4 --ranges "0:00-1:30, 3:00-19:00"
python -m subtool transcribe 영상.mp4 --ranges "1:30-3:00" --replace     # 구간만 다시 / 추가
python -m subtool transcribe 영상.mp4 --glossary 용어집.csv --model large-v3
python -m subtool sync 영상.mp4 --offset -0.5        # 전체 0.5초 앞으로
python -m subtool sync 영상.mp4 --auto               # ffsubsync 자동 맞춤
python -m subtool export 영상.mp4 --format txt,timestamped,srt,vtt,mkv
```
- 이미 자막이 있는 영상을 처음부터 다시 받아쓰려면 `--force` (편집한 내용은 사라집니다).
- 구간 받아쓰기는 경계 앞뒤 0.5초를 더 뽑아 단어가 잘리지 않게 하고, 구간 바로 앞 자막을 문맥 힌트로 넘깁니다.

## 만들어지는 파일 (영상과 같은 폴더)
| 파일 | 내용 |
|---|---|
| `영상.mp4.subtool.json` | 자막 문서 (타이밍 + 언어별 텍스트 + 단어별 시각·확신도 + 실행 명령 이력) |
| `영상.srt` | 영어 자막 (저장할 때마다 갱신) |
| `영상.orig.srt` | 처음 저장 직전의 SRT 백업 |
| `영상.txt` / `영상.timestamped.txt` | 읽기용 텍스트 / 문단마다 `[mm:ss]` |
| `영상.vtt` | WebVTT 자막 |
| `영상.subtitled.mkv` | 자막 트랙을 넣은 영상 (재인코딩 없음, 원본은 그대로) |

## 용어집
CSV(UTF-8) 형식이며 `examples/`에 예시가 있습니다. 다음 순서로 합쳐서 씁니다 (뒤가 앞을 덮어씀).
1. 기본 용어집: `~/.subtool/glossary_en.csv`
2. 시리즈 용어집: 영상과 같은 폴더의 `glossary_en.csv`
3. `--glossary`로 지정한 파일

| 열 | 의미 |
|---|---|
| `term` | 올바른 표기 |
| `variants` | 자주 잘못 인식되는 형태, `\|`로 구분 → 받아쓰기 직후 자동 치환 (대소문자 무시, 단어 경계 기준) |
| `type` | person / place / term 등 |
| `hint` | `Y`면 받아쓰기 힌트로 넣음 (Whisper initial_prompt) |
| `note` | 메모 |

`glossary_ko.csv`(번역용)는 형식만 정해 두었고 아직 쓰지 않습니다.

## 테스트
```bash
python tests/test_core.py
```
모델 없이 시각 변환, 구간, 자막 분할, 용어집, SRT, 텍스트 추출을 확인합니다.

## 알려진 한계
- 브라우저가 재생하지 못하는 코덱(예: 일부 HEVC MKV)은 편집 화면에서 재생되지 않습니다. 받아쓰기와 내보내기는 됩니다.
- Windows는 작업 완료 시스템 알림이 없고 화면 표시로만 알려 줍니다.
- `mlx-whisper` 엔진은 Apple Silicon에서만 동작하며, 이 저장소의 최초 버전은 Windows에서 `faster-whisper`로 검증했습니다.

## 진행 상황
설계 문서는 [BRIEF.md](BRIEF.md)에 있습니다. 구현 순서 1~4단계(받아쓰기 CLI, 웹 기본, 플레이어 싱크, 텍스트 추출)가 들어 있고, 5단계 이후(품질·환각 검사, 파형 타임라인, 시리즈·검수 연동 등)는 아직입니다.
