# =====================================================================
# 프론트엔드(React + Vite) 멀티스테이지 Dockerfile.
# deps: npm 의존성만 설치하는 공통 베이스 스테이지.
# dev: docker-compose 로컬 개발용 (바인드 마운트로 소스를 덮어써 핫리로드).
# build: 정적 프로덕션 빌드(dist/)를 생성하는 스테이지.
# production: nginx로 build 산출물을 서빙하는 최종 이미지.
# =====================================================================

# 의존성 설치 전용 1단계 시작 (베이스: node 22 alpine)
FROM node:22-alpine AS deps
# 작업 디렉토리 설정
WORKDIR /app
# 패키지 정의 파일만 먼저 복사 (레이어 캐시 최적화)
COPY package.json package-lock.json ./
# lock 파일 기준으로 정확한 버전의 의존성 설치
RUN npm ci

# Used by docker-compose for local dev (hot reload via bind mount).
# docker-compose 로컬 개발용 (바인드 마운트를 통한 핫리로드)
# 개발용 스테이지: deps 스테이지를 기반으로 함
FROM deps AS dev
# 전체 소스 복사 (실제로는 docker-compose가 바인드 마운트로 덮어씀)
COPY . .
# Vite 개발 서버 기본 포트 노출
EXPOSE 5173
# 컨테이너 밖에서도 접근 가능하도록 0.0.0.0으로 Vite dev 서버 실행
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# 프로덕션 정적 빌드용 스테이지: deps 스테이지를 기반으로 함
FROM deps AS build
# 전체 소스 복사
COPY . .
# Empty by default: app's fetch paths already start with /api/v1, so a
# same-origin relative request lets the Ingress route /api -> backend
# without a doubled prefix. Override only if the API lives elsewhere.
# 기본값은 빈 문자열: 앱의 fetch 경로가 이미 /api/v1로 시작하므로 same-origin
# 상대경로 요청이 되어 Ingress가 /api를 backend로 라우팅해준다(중복 프리픽스
# 없이). API가 다른 곳에 있을 때만 override.
ARG VITE_API_URL=
# ARG 값을 ENV로 넘겨 npm run build 시 Vite가 이 값을 번들에 굽도록 함
ENV VITE_API_URL=$VITE_API_URL
# tsc 빌드 + Vite 프로덕션 빌드 실행 (정적 파일 dist/ 생성)
RUN npm run build

# 최종 서빙용 스테이지: 경량 nginx 베이스 이미지 사용
FROM nginx:1.27-alpine AS production
# build 스테이지 산출물(dist)을 nginx 정적 파일 경로로 복사
COPY --from=build /app/dist /usr/share/nginx/html
# 커스텀 nginx 설정을 기본 설정 위치에 복사
COPY nginx.conf /etc/nginx/conf.d/default.conf
# nginx 기본 포트 노출
EXPOSE 80
# 헬스체크 정의: 30초 간격, 3초 타임아웃, 시작 후 5초 유예
# 루트 경로 응답 여부로 정상 동작 확인. localhost 대신 127.0.0.1을 명시하는 이유:
# 일부 환경(IPv6 루프백은 있지만 nginx가 IPv4만 리스닝하는 컨테이너 네트워크)에서
# "localhost"가 ::1로 먼저 해석되어 연결이 거부되는 경우가 있다.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
