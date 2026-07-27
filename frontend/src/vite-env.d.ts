/// <reference types="vite/client" />

// import.meta.env로 접근하는 환경변수에 타입을 붙여주기 위한 선언 파일.
// 이게 없으면 TypeScript가 VITE_API_URL을 알지 못해 타입 에러가 난다.
interface ImportMetaEnv {
  readonly VITE_API_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
