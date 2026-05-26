import { Button, Form, Input, Card, Typography, message, Space } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'

const { Title } = Typography

interface ChangePasswordForm {
  current_password: string
  new_password: string
  confirm_password: string
}

export default function ChangePassword() {
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const [form] = Form.useForm()

  const onFinish = async (values: ChangePasswordForm) => {
    if (values.new_password !== values.confirm_password) {
      message.error('Passwords do not match')
      return
    }
    setLoading(true)
    try {
      await client.post('/auth/change-password', {
        current_password: values.current_password,
        new_password: values.new_password,
      })
      message.success('Password changed successfully')
      navigate('/')
    } catch (err: any) {
      message.error(err.response?.data?.detail || 'Failed to change password')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 480, margin: '0 auto' }}>
      <Card>
        <Title level={4} style={{ marginBottom: 24 }}>Change Password</Title>
        <Form form={form} layout="vertical" onFinish={onFinish}>
          <Form.Item
            name="current_password"
            label="Current Password"
            rules={[{ required: true, message: 'Please enter current password' }]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="New Password"
            rules={[
              { required: true, message: 'Please enter new password' },
              { min: 4, message: 'Password must be at least 4 characters' },
            ]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label="Confirm New Password"
            dependencies={['new_password']}
            rules={[
              { required: true, message: 'Please confirm new password' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('new_password') === value) {
                    return Promise.resolve()
                  }
                  return Promise.reject(new Error('Passwords do not match'))
                },
              }),
            ]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={loading}>
                Change Password
              </Button>
              <Button onClick={() => navigate('/')}>Cancel</Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}
