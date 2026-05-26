import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import AppLayout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Entities from './pages/Entities'
import KnowledgeUnits from './pages/KnowledgeUnits'
import EventClusters from './pages/EventClusters'
import Articles from './pages/Articles'
import Processing from './pages/Processing'
import Neo4jGuide from './pages/Neo4jGuide'

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter basename="/admin">
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/entities" element={<Entities />} />
            <Route path="/knowledge-units" element={<KnowledgeUnits />} />
            <Route path="/event-clusters" element={<EventClusters />} />
            <Route path="/articles" element={<Articles />} />
            <Route path="/processing" element={<Processing />} />
            <Route path="/neo4j" element={<Neo4jGuide />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  )
}
