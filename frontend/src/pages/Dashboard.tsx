import { useEffect, useState } from 'react'
import { Row, Col, Card, Statistic, Spin, Typography, Tag, Space } from 'antd'
import {
  TeamOutlined,
  FileTextOutlined,
  ClusterOutlined,
  ReadOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  SyncOutlined,
  PauseCircleOutlined,
} from '@ant-design/icons'
import { fetchDashboardStats } from '../api/dashboard'
import { fetchPipelineStatus, fetchContainerStatuses } from '../api/processing'
import type { DashboardStats, PipelineStatus, ContainerStatus } from '../api/types'

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [pipeline, setPipeline] = useState<PipelineStatus | null>(null)
  const [containers, setContainers] = useState<ContainerStatus[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchDashboardStats()
      .then(setStats)
      .finally(() => setLoading(false))
    fetchPipelineStatus().then(setPipeline).catch(() => {})
    fetchContainerStatuses().then(setContainers).catch(() => {})
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

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card title="Pipeline Status">
            <Space direction="vertical" style={{ width: '100%' }}>
              <Space>
                {pipeline?.fetch.running
                  ? <SyncOutlined spin style={{ color: '#1890ff' }} />
                  : <PauseCircleOutlined style={{ color: '#8c8c8c' }} />}
                <Typography.Text strong>Fetch:</Typography.Text>
                <Tag color={pipeline?.fetch.running ? 'green' : 'default'}>
                  {pipeline?.fetch.running ? 'Running' : 'Stopped'}
                </Tag>
                {pipeline?.fetch.started_at && (
                  <Typography.Text type="secondary">
                    since {new Date(pipeline.fetch.started_at).toLocaleString()}
                  </Typography.Text>
                )}
              </Space>
              <Space>
                {pipeline?.offline.running
                  ? <SyncOutlined spin style={{ color: '#1890ff' }} />
                  : <PauseCircleOutlined style={{ color: '#8c8c8c' }} />}
                <Typography.Text strong>Offline:</Typography.Text>
                <Tag color={pipeline?.offline.running ? 'green' : 'default'}>
                  {pipeline?.offline.running ? 'Running' : 'Stopped'}
                </Tag>
                {pipeline?.offline.started_at && (
                  <Typography.Text type="secondary">
                    since {new Date(pipeline.offline.started_at).toLocaleString()}
                  </Typography.Text>
                )}
              </Space>
              {pipeline?.mode && (
                <Typography.Text type="secondary">Detection mode: {pipeline.mode}</Typography.Text>
              )}
            </Space>
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Container Status">
            <Space direction="vertical" style={{ width: '100%' }}>
              {containers.map((c) => (
                <Space key={c.name}>
                  {c.running
                    ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
                    : <CloseCircleOutlined style={{ color: '#ff4d4f' }} />}
                  <Typography.Text strong>{c.name}:</Typography.Text>
                  <Tag color={c.running ? 'green' : 'red'}>
                    {c.running ? 'Running' : 'Stopped'}
                  </Tag>
                  <Typography.Text type="secondary">{c.status}</Typography.Text>
                </Space>
              ))}
              {containers.length === 0 && (
                <Typography.Text type="secondary">Container status unavailable (local dev mode)</Typography.Text>
              )}
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
