import { useEffect, useState, useCallback } from 'react'
import { Table, Input, Drawer, Tabs, Descriptions, Tag, Space, Typography, Select } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { fetchKnowledgeUnits, fetchKnowledgeUnit, fetchKURelatedEntities } from '../api/knowledge-units'
import type { KUSummary, EntitySummary } from '../api/types'

const conflictColors: Record<string, string> = {
  none: 'green',
  possible: 'orange',
  confirmed: 'red',
}

const columns: ColumnsType<KUSummary> = [
  { title: 'Type', dataIndex: 'unit_type', width: 160, ellipsis: true },
  { title: 'Summary', dataIndex: 'summary', ellipsis: true },
  {
    title: 'Kind',
    dataIndex: 'unit_kind',
    width: 80,
    render: (v: string) => <Tag>{v}</Tag>,
  },
  {
    title: 'Published',
    dataIndex: 'published_at',
    width: 180,
    render: (v: string) => new Date(v).toLocaleString(),
  },
  {
    title: 'Conflict',
    dataIndex: 'conflict_status',
    width: 90,
    render: (v: string) => <Tag color={conflictColors[v] || 'default'}>{v}</Tag>,
  },
]

const entityColumns: ColumnsType<EntitySummary> = [
  { title: 'Name', dataIndex: 'canonical_name' },
  {
    title: 'Type',
    dataIndex: 'entity_type',
    width: 120,
    render: (v: string) => <Tag color="blue">{v || 'Unknown'}</Tag>,
  },
]

export default function KnowledgeUnits() {
  const [data, setData] = useState<KUSummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [unitKind, setUnitKind] = useState('')
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const navigate = useNavigate()

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchKnowledgeUnits(page, pageSize, search, '', unitKind)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, search, unitKind])

  useEffect(() => { loadData() }, [loadData])

  useEffect(() => {
    const autoOpen = sessionStorage.getItem('autoOpenKU')
    if (autoOpen) {
      sessionStorage.removeItem('autoOpenKU')
      fetchKnowledgeUnit(autoOpen).then((d) => { setDetail(d); setDetailId(autoOpen); setDrawerOpen(true) }).catch(() => {})
    }
  }, [])

  const handleRowClick = async (record: KUSummary) => {
    const d = await fetchKnowledgeUnit(record.ku_id)
    setDetail(d)
    setDetailId(record.ku_id)
    setDrawerOpen(true)
  }

  const openEntity = (entityId: string) => {
    setDrawerOpen(false)
    sessionStorage.setItem('autoOpenEntity', entityId)
    navigate('/entities')
  }

  const displayValue = (value: unknown): string => {
    if (Array.isArray(value)) return value.length > 0 ? JSON.stringify(value) : '[]'
    if (typeof value === 'object' && value !== null) return JSON.stringify(value, null, 2)
    return String(value ?? '')
  }

  const basicInfoFields = detail
    ? Object.entries(detail).filter(([, v]) => typeof v !== 'object' || v === null || Array.isArray(v))
    : []

  const tabs = detail ? [
    {
      key: 'info',
      label: 'Basic Info',
      children: (
        <Descriptions column={1} bordered size="small">
          {basicInfoFields.map(([key, value]) => (
            <Descriptions.Item key={key} label={key}>
              {displayValue(value)}
            </Descriptions.Item>
          ))}
        </Descriptions>
      ),
    },
    {
      key: 'entities',
      label: 'Entities',
      children: (
        <RelatedEntitiesTable kuId={detailId!} onEntityClick={openEntity} />
      ),
    },
  ] : []

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="Search knowledge units..."
          allowClear
          onSearch={setSearch}
          style={{ width: 300 }}
        />
        <Select
          placeholder="Unit kind"
          allowClear
          style={{ width: 140 }}
          value={unitKind || undefined}
          onChange={(v) => setUnitKind(v || '')}
          options={[
            { value: 'event', label: 'Event' },
            { value: 'relation', label: 'Relation' },
            { value: 'fact', label: 'Fact' },
          ]}
        />
      </Space>

      <Table<KUSummary>
        columns={columns}
        dataSource={data}
        rowKey="ku_id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `Total ${t}`,
          onChange: (p, ps) => { setPage(p); setPageSize(ps) },
        }}
        onRow={(record) => ({ onClick: () => handleRowClick(record), style: { cursor: 'pointer' } })}
        size="small"
      />

      <Drawer
        title="Knowledge Unit Detail"
        width={720}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        {detail && <Tabs items={tabs} />}
      </Drawer>
    </div>
  )
}

function RelatedEntitiesTable({ kuId, onEntityClick }: { kuId: string; onEntityClick: (id: string) => void }) {
  const [data, setData] = useState<EntitySummary[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetchKURelatedEntities(kuId)
      .then(setData)
      .finally(() => setLoading(false))
  }, [kuId])

  return (
    <Table<EntitySummary>
      columns={entityColumns}
      dataSource={data}
      rowKey="entity_id"
      loading={loading}
      size="small"
      pagination={false}
      onRow={(r) => ({ onClick: () => onEntityClick(r.entity_id), style: { cursor: 'pointer' } })}
      footer={() => <Typography.Text type="secondary">Total {data.length}</Typography.Text>}
    />
  )
}
