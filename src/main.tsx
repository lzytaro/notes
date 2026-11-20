import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import WidgetApp from './WidgetApp'
import './styles.css'

const widgetKind = new URLSearchParams(window.location.search).get('widget') as 'next' | 'today' | 'capture' | null

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {widgetKind ? <WidgetApp kind={widgetKind} /> : <App />}
  </StrictMode>,
)
