import { useState } from 'react'
import { Layout, Menu, Typography } from 'antd'
import {
  DashboardOutlined,
  TeamOutlined,
  FileTextOutlined,
  ClusterOutlined,
  ReadOutlined,
  SettingOutlined,
  ApartmentOutlined,
} from '@ant-design/icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'

const { Sider, Content, Header } = Layout
const { Title } = Typography

const neo4jUrl = `${window.location.origin}/neo4j/browser/`

const menuItems = [
  { key: '/', icon: <DashboardOutlined />, label: 'Dashboard' },
  { key: '/entities', icon: <TeamOutlined />, label: 'Entities' },
  { key: '/knowledge-units', icon: <FileTextOutlined />, label: 'Knowledge Units' },
  { key: '/event-clusters', icon: <ClusterOutlined />, label: 'Event Clusters' },
  { key: '/articles', icon: <ReadOutlined />, label: 'Articles' },
  { key: '/processing', icon: <SettingOutlined />, label: 'Processing' },
  { key: '__neo4j__', icon: <ApartmentOutlined />, label: 'Graph (Neo4j)' },
]

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed}>
        <div style={{ padding: '16px 16px 8px', textAlign: 'center' }}>
          <Title level={collapsed ? 5 : 4} style={{ color: '#fff', margin: 0, whiteSpace: 'nowrap' }}>
            {collapsed ? 'K' : 'Knowledge'}
          </Title>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => {
            if (key === '__neo4j__') {
              window.open(neo4jUrl, '_blank')
            } else {
              navigate(key)
            }
          }}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px', borderBottom: '1px solid #f0f0f0' }}>
          <Title level={4} style={{ margin: '14px 0' }}>Knowledge Admin</Title>
        </Header>
        <Content style={{ margin: 24 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
