import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import AppLayout from './components/Layout'
import AuthGuard from './components/AuthGuard'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Entities from './pages/Entities'
import KnowledgeUnits from './pages/KnowledgeUnits'
import EventClusters from './pages/EventClusters'
import Articles from './pages/Articles'
import Processing from './pages/Processing'
import AuditLog from './pages/AuditLog'
import Neo4jGuide from './pages/Neo4jGuide'
import Users from './pages/Users'
import ChangePassword from './pages/ChangePassword'

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter basename="/admin">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            element={
              <AuthGuard>
                <AppLayout />
              </AuthGuard>
            }
          >
            <Route path="/" element={<Dashboard />} />
            <Route path="/entities" element={<Entities />} />
            <Route path="/knowledge-units" element={<KnowledgeUnits />} />
            <Route path="/event-clusters" element={<EventClusters />} />
            <Route path="/articles" element={<Articles />} />
            <Route path="/processing" element={<Processing />} />
            <Route path="/audit-log" element={<AuditLog />} />
            <Route path="/neo4j" element={<Neo4jGuide />} />
            <Route path="/users" element={<Users />} />
            <Route path="/change-password" element={<ChangePassword />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  )
}
