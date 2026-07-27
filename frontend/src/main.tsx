// 앱의 진입점(entry point). index.html의 <div id="root">에 React 트리를 붙인다.
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// StrictMode: 개발 중에만 잠재적 버그를 찾기 위해 일부 로직을 일부러 두 번 실행해보는 모드.
// 프로덕션 빌드에는 영향을 주지 않는다.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
