import { useState, useEffect } from 'react'
import { Layout, Menu, Typography, Dropdown, Avatar, Space } from 'antd'
import {
  DashboardOutlined,
  TeamOutlined,
  FileTextOutlined,
  ClusterOutlined,
  ReadOutlined,
  SettingOutlined,
  ApartmentOutlined,
  UserOutlined,
  LogoutOutlined,
  KeyOutlined,
} from '@ant-design/icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { clearTokens } from '../api/client'

const { Sider, Content, Header } = Layout
const { Title } = Typography

const menuItems = [
  { key: '/', icon: <DashboardOutlined />, label: 'Dashboard' },
  { key: '/entities', icon: <TeamOutlined />, label: 'Entities' },
  { key: '/knowledge-units', icon: <FileTextOutlined />, label: 'Knowledge Units' },
  { key: '/event-clusters', icon: <ClusterOutlined />, label: 'Event Clusters' },
  { key: '/articles', icon: <ReadOutlined />, label: 'Articles' },
  { key: '/processing', icon: <SettingOutlined />, label: 'Processing' },
  { key: '/neo4j', icon: <ApartmentOutlined />, label: 'Graph (Neo4j)' },
  { key: '/users', icon: <TeamOutlined />, label: 'Users' },
]

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const [username, setUsername] = useState('')
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    const stored = localStorage.getItem('access_token')
    if (stored) {
      try {
        const payload = JSON.parse(atob(stored.split('.')[1]))
        setUsername(payload.username || '')
      } catch { /* ignore */ }
    }
  }, [])

  const handleLogout = () => {
    clearTokens()
    navigate('/login')
  }

  const userMenu = {
    items: [
      { key: 'change-password', icon: <KeyOutlined />, label: 'Change Password' },
      { type: 'divider' as const },
      { key: 'logout', icon: <LogoutOutlined />, label: 'Sign out', danger: true },
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === 'logout') handleLogout()
      if (key === 'change-password') navigate('/change-password')
    },
  }

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
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header style={{
          background: '#fff',
          padding: '0 24px',
          borderBottom: '1px solid #f0f0f0',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <Title level={4} style={{ margin: '14px 0' }}>Knowledge Admin</Title>
          <Dropdown menu={userMenu} placement="bottomRight">
            <Space style={{ cursor: 'pointer' }}>
              <Avatar size="small" icon={<UserOutlined />} />
              <span>{username || 'User'}</span>
            </Space>
          </Dropdown>
        </Header>
        <Content style={{ margin: 24 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
