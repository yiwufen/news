import { useEffect, useState } from 'react'
import { Row, Col, Card, Statistic, Spin, Typography, Tag, Space } from 'antd'
import {
  TeamOutlined,
  FileTextOutlined,
  ClusterOutlined,
  ReadOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons'
import { fetchDashboardStats } from '../api/dashboard'
import type { DashboardStats } from '../api/types'

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchDashboardStats()
      .then(setStats)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin size="large" style={{ display: 'block', marginTop: 100 }} />
  if (!stats) return <Typography.Text type="danger">Failed to load stats</Typography.Text>

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col span={6}>
          <Card>
            <Statistic title="Entities" value={stats.entities.total} prefix={<TeamOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="Knowledge Units" value={stats.knowledge_units.total} prefix={<FileTextOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="Event Clusters" value={stats.event_clusters.total} prefix={<ClusterOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="Articles" value={stats.articles.total} prefix={<ReadOutlined />} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card title="Entity Types">
            <Space wrap>
              {Object.entries(stats.entities.by_type).map(([type, count]) => (
                <Tag key={type} color="blue">{type || 'Unknown'}: {count}</Tag>
              ))}
            </Space>
          </Card>
        </Col>
        <Col span={12}>
          <Card title="KU Kinds">
            <Space wrap>
              {Object.entries(stats.knowledge_units.by_kind).map(([kind, count]) => (
                <Tag key={kind} color="green">{kind}: {count}</Tag>
              ))}
            </Space>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card title="Article Categories">
            <Space wrap>
              {Object.entries(stats.articles.by_category).map(([cat, count]) => (
                <Tag key={cat}>{cat}: {count}</Tag>
              ))}
            </Space>
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Processing">
            <Space direction="vertical" style={{ width: '100%' }}>
              <Statistic
                title="Processed"
                value={stats.processing.total_processed}
                prefix={<CheckCircleOutlined />}
                valueStyle={{ color: '#3f8600' }}
              />
              <Statistic
                title="Failed"
                value={stats.processing.total_failed}
                prefix={<CloseCircleOutlined />}
                valueStyle={{ color: '#cf1322' }}
              />
              <Typography.Text type="secondary">
                Last processed: {stats.processing.last_processed_at || 'N/A'}
              </Typography.Text>
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
