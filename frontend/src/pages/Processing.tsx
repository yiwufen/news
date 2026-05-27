import { useEffect, useState, useCallback } from 'react'
import { Table, Tag, Alert, Space, Typography, Button, message } from 'antd'
import { SyncOutlined, ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { fetchProcessingLog, fetchPipelineStatus } from '../api/processing'
import { reprocessDocument } from '../api/reprocessing'
import type { ProcessingLogEntry, PipelineStatus } from '../api/types'

const statusColors: Record<string, string> = {
  processed: 'green',
  failed: 'red',
  pending: 'orange',
  processing: 'blue',
  success: 'green',
  partial: 'orange',
}

export default function Processing() {
  const [data, setData] = useState<ProcessingLogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [pipeline, setPipeline] = useState<PipelineStatus | null>(null)
  const [reprocessing, setReprocessing] = useState<Set<string>>(new Set())

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchProcessingLog(page, pageSize)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize])

  useEffect(() => { loadData() }, [loadData])
  useEffect(() => { fetchPipelineStatus().then(setPipeline).catch(() => {}) }, [])

  const handleReprocess = async (docId: string) => {
    setReprocessing((prev) => new Set(prev).add(docId))
    try {
      const result = await reprocessDocument(docId)
      message.success(`Reprocessed ${docId}: ${result.status}`)
      loadData()
    } catch {
      message.error(`Failed to reprocess ${docId}`)
    } finally {
      setReprocessing((prev) => { const next = new Set(prev); next.delete(docId); return next })
    }
  }

  const columns: ColumnsType<ProcessingLogEntry> = [
    { title: 'Doc ID', dataIndex: 'doc_id', width: 200, ellipsis: true },
    {
      title: 'Status',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => <Tag color={statusColors[v] || 'default'}>{v}</Tag>,
    },
    { title: 'KUs', dataIndex: 'knowledge_units_count', width: 80, align: 'center' },
    { title: 'Entities', dataIndex: 'entities_count', width: 80, align: 'center' },
    { title: 'Clusters', dataIndex: 'clusters_count', width: 80, align: 'center' },
    { title: 'Error', dataIndex: 'error_message', ellipsis: true, render: (v: string | null) => v || '-' },
    { title: 'Updated', dataIndex: 'updated_at', width: 180, render: (v: string) => new Date(v).toLocaleString() },
    {
      title: 'Action',
      width: 120,
      render: (_: unknown, record: ProcessingLogEntry) => (
        <Button
          size="small"
          icon={<ReloadOutlined />}
          loading={reprocessing.has(record.doc_id)}
          onClick={() => handleReprocess(record.doc_id)}
        >
          Rerun
        </Button>
      ),
    },
  ]

  return (
    <div>
      {pipeline && (
        <Alert
          type={pipeline.offline.running ? 'info' : 'warning'}
          message={
            <Space>
              <Typography.Text strong>Fetch:</Typography.Text>
              <Tag color={pipeline.fetch.running ? 'green' : 'default'}>
                {pipeline.fetch.running ? <><SyncOutlined spin /> Running</> : 'Stopped'}
              </Tag>
              <Typography.Text strong>Offline:</Typography.Text>
              <Tag color={pipeline.offline.running ? 'green' : 'default'}>
                {pipeline.offline.running ? <><SyncOutlined spin /> Running</> : 'Stopped'}
              </Tag>
              <Typography.Text type="secondary">mode: {pipeline.mode}</Typography.Text>
            </Space>
          }
          style={{ marginBottom: 16 }}
          showIcon
        />
      )}
      <Table<ProcessingLogEntry>
        columns={columns}
        dataSource={data}
        rowKey="doc_id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `Total ${t}`,
          onChange: (p, ps) => { setPage(p); setPageSize(ps) },
        }}
        size="small"
      />
    </div>
  )
}
