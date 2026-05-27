import { useEffect, useState, useCallback } from 'react'
import { Table, Tag, Space, Button, Select, message, Typography, Modal } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { fetchAuditLog, undoAuditEntry } from '../api/audit'
import type { AuditLogEntry } from '../api/types'

const actionColors: Record<string, string> = {
  'entity.edit': 'blue',
  'entity.merge': 'orange',
  'entity.split': 'purple',
  'entity.delete': 'red',
  'cluster.edit': 'blue',
  'cluster.merge': 'orange',
  'cluster.split': 'purple',
  'cluster.delete': 'red',
  'doc.reprocess': 'green',
}

export default function AuditLog() {
  const [data, setData] = useState<AuditLogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [actionFilter, setActionFilter] = useState('')
  const [resourceFilter, setResourceFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [detailEntry, setDetailEntry] = useState<AuditLogEntry | null>(null)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchAuditLog(page, pageSize, actionFilter, resourceFilter)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, actionFilter, resourceFilter])

  useEffect(() => { loadData() }, [loadData])

  const handleUndo = async (logId: number) => {
    try {
      const result = await undoAuditEntry(logId)
      message.success(result.message)
      loadData()
    } catch {
      message.error('Undo failed')
    }
  }

  const columns: ColumnsType<AuditLogEntry> = [
    { title: 'Time', dataIndex: 'created_at', width: 180, render: (v: string) => new Date(v).toLocaleString() },
    { title: 'User', dataIndex: 'username', width: 100 },
    {
      title: 'Action',
      dataIndex: 'action',
      width: 160,
      render: (v: string) => <Tag color={actionColors[v] || 'default'}>{v}</Tag>,
    },
    { title: 'Resource', dataIndex: 'resource_type', width: 100 },
    { title: 'Resource ID', dataIndex: 'resource_id', ellipsis: true },
    {
      title: 'Actions',
      width: 120,
      render: (_: unknown, record: AuditLogEntry) => (
        <Space>
          <Button size="small" onClick={() => setDetailEntry(record)}>View</Button>
          {!record.action.startsWith('undo.') && record.resource_type !== 'document' && (
            <Button size="small" danger onClick={() => handleUndo(record.id)}>Undo</Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Select
          placeholder="Action"
          allowClear
          style={{ width: 180 }}
          value={actionFilter || undefined}
          onChange={(v) => setActionFilter(v || '')}
          options={Object.keys(actionColors).map((a) => ({ value: a, label: a }))}
        />
        <Select
          placeholder="Resource type"
          allowClear
          style={{ width: 150 }}
          value={resourceFilter || undefined}
          onChange={(v) => setResourceFilter(v || '')}
          options={[
            { value: 'entity', label: 'Entity' },
            { value: 'cluster', label: 'Cluster' },
            { value: 'document', label: 'Document' },
          ]}
        />
      </Space>

      <Table<AuditLogEntry>
        columns={columns}
        dataSource={data}
        rowKey="id"
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

      <Modal
        title={`Audit Log #${detailEntry?.id}`}
        open={!!detailEntry}
        onCancel={() => setDetailEntry(null)}
        footer={null}
        width={700}
      >
        {detailEntry && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <div>
              <Typography.Text strong>Action: </Typography.Text>
              <Tag color={actionColors[detailEntry.action] || 'default'}>{detailEntry.action}</Tag>
              <Typography.Text type="secondary"> by {detailEntry.username} at {new Date(detailEntry.created_at).toLocaleString()}</Typography.Text>
            </div>
            <div>
              <Typography.Text strong>Old State</Typography.Text>
              <pre style={{ maxHeight: 300, overflow: 'auto', background: '#f5f5f5', padding: 8, borderRadius: 4, fontSize: 12 }}>
                {detailEntry.old_state ? JSON.stringify(detailEntry.old_state, null, 2) : 'N/A'}
              </pre>
            </div>
            <div>
              <Typography.Text strong>New State</Typography.Text>
              <pre style={{ maxHeight: 300, overflow: 'auto', background: '#f5f5f5', padding: 8, borderRadius: 4, fontSize: 12 }}>
                {detailEntry.new_state ? JSON.stringify(detailEntry.new_state, null, 2) : 'N/A'}
              </pre>
            </div>
            {detailEntry.metadata && (
              <div>
                <Typography.Text strong>Metadata</Typography.Text>
                <pre style={{ maxHeight: 200, overflow: 'auto', background: '#f5f5f5', padding: 8, borderRadius: 4, fontSize: 12 }}>
                  {JSON.stringify(detailEntry.metadata, null, 2)}
                </pre>
              </div>
            )}
          </Space>
        )}
      </Modal>
    </div>
  )
}
