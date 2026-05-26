import { useState, useEffect, useCallback } from 'react'
import {
  Table, Button, Modal, Form, Input, Select, Switch,
  Space, Tag, Popconfirm, message, Typography,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { fetchUsers, createUser, updateUser, deleteUser, UserInfo } from '../api/users'

const { Title } = Typography

export default function Users() {
  const [users, setUsers] = useState<UserInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingUser, setEditingUser] = useState<UserInfo | null>(null)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchUsers()
      setUsers(data)
    } catch { message.error('Failed to load users') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const openCreate = () => {
    setEditingUser(null)
    form.resetFields()
    form.setFieldsValue({ role: 'viewer', display_name: '' })
    setModalOpen(true)
  }

  const openEdit = (user: UserInfo) => {
    setEditingUser(user)
    form.setFieldsValue({
      username: user.username,
      display_name: user.display_name,
      role: user.role,
      is_active: user.is_active,
    })
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    try {
      if (editingUser) {
        await updateUser(editingUser.id, values)
        message.success('User updated')
      } else {
        await createUser(values)
        message.success('User created')
      }
      setModalOpen(false)
      load()
    } catch (err: any) {
      message.error(err.response?.data?.detail || 'Operation failed')
    }
  }

  const handleDelete = async (id: number) => {
    try {
      await deleteUser(id)
      message.success('User deleted')
      load()
    } catch (err: any) {
      message.error(err.response?.data?.detail || 'Delete failed')
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: 'Username', dataIndex: 'username' },
    { title: 'Display Name', dataIndex: 'display_name' },
    {
      title: 'Role', dataIndex: 'role', width: 100,
      render: (role: string) => (
        <Tag color={role === 'admin' ? 'red' : 'blue'}>{role}</Tag>
      ),
    },
    {
      title: 'Status', dataIndex: 'is_active', width: 100,
      render: (v: boolean) => v ? <Tag color="green">Active</Tag> : <Tag color="default">Inactive</Tag>,
    },
    { title: 'Last Login', dataIndex: 'last_login_at', width: 180 },
    {
      title: 'Actions', key: 'actions', width: 120,
      render: (_: unknown, record: UserInfo) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          <Popconfirm title="Delete this user?" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>User Management</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>New User</Button>
      </div>
      <Table
        dataSource={users}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={false}
      />
      <Modal
        title={editingUser ? 'Edit User' : 'New User'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="username"
            label="Username"
            rules={[{ required: true, min: 2, max: 64 }]}
          >
            <Input disabled={!!editingUser} />
          </Form.Item>
          <Form.Item
            name="password"
            label={editingUser ? 'New Password (leave blank to keep)' : 'Password'}
            rules={editingUser ? [] : [{ required: true, min: 4, max: 128 }]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item name="display_name" label="Display Name">
            <Input />
          </Form.Item>
          <Form.Item name="role" label="Role" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'viewer', label: 'Viewer (read-only)' },
                { value: 'admin', label: 'Admin (full access)' },
              ]}
            />
          </Form.Item>
          {editingUser && (
            <Form.Item name="is_active" label="Active" valuePropName="checked">
              <Switch />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  )
}
