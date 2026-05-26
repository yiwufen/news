import { useEffect, useState, useCallback } from 'react'
import { Table, Drawer, Tabs, Descriptions, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { fetchEventClusters, fetchEventCluster, fetchClusterMemberKUs, fetchClusterRelatedEntities } from '../api/event-clusters'
import type { ClusterSummary, KUSummary, EntitySummary } from '../api/types'

const conflictColors: Record<string, string> = {
  none: 'green',
  possible: 'orange',
  confirmed: 'red',
}

const columns: ColumnsType<ClusterSummary> = [
  { title: 'Title', dataIndex: 'title', ellipsis: true },
  { title: 'Type', dataIndex: 'cluster_type', width: 160, ellipsis: true },
  { title: 'Members', dataIndex: 'member_count', width: 90, align: 'center' },
  { title: 'Sources', dataIndex: 'source_count', width: 90, align: 'center' },
  {
    title: 'Conflict',
    dataIndex: 'conflict_status',
    width: 90,
    render: (v: string) => <Tag color={conflictColors[v] || 'default'}>{v}</Tag>,
  },
  {
    title: 'Updated',
    dataIndex: 'updated_at',
    width: 180,
    render: (v: string) => new Date(v).toLocaleString(),
  },
]

const kuColumns: ColumnsType<KUSummary> = [
  { title: 'Type', dataIndex: 'unit_type', width: 160, ellipsis: true },
  { title: 'Summary', dataIndex: 'summary', ellipsis: true },
  {
    title: 'Published',
    dataIndex: 'published_at',
    width: 160,
    render: (v: string) => new Date(v).toLocaleString(),
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

export default function EventClusters() {
  const [data, setData] = useState<ClusterSummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const navigate = useNavigate()

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchEventClusters(page, pageSize)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize])

  useEffect(() => { loadData() }, [loadData])

  useEffect(() => {
    const autoOpen = sessionStorage.getItem('autoOpenCluster')
    if (autoOpen) {
      sessionStorage.removeItem('autoOpenCluster')
      fetchEventCluster(autoOpen).then((d) => { setDetail(d); setDetailId(autoOpen); setDrawerOpen(true) }).catch(() => {})
    }
  }, [])

  const handleRowClick = async (record: ClusterSummary) => {
    const d = await fetchEventCluster(record.cluster_id)
    setDetail(d)
    setDetailId(record.cluster_id)
    setDrawerOpen(true)
  }

  const openKU = (kuId: string) => {
    setDrawerOpen(false)
    sessionStorage.setItem('autoOpenKU', kuId)
    navigate('/knowledge-units')
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
      key: 'kus',
      label: 'Member KUs',
      children: (
        <MemberKUsTable clusterId={detailId!} onKUClick={openKU} />
      ),
    },
    {
      key: 'entities',
      label: 'Entities',
      children: (
        <ClusterEntitiesTable clusterId={detailId!} onEntityClick={openEntity} />
      ),
    },
  ] : []

  return (
    <div>
      <Table<ClusterSummary>
        columns={columns}
        dataSource={data}
        rowKey="cluster_id"
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
        title="Event Cluster Detail"
        width={720}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        {detail && <Tabs items={tabs} />}
      </Drawer>
    </div>
  )
}

function MemberKUsTable({ clusterId, onKUClick }: { clusterId: string; onKUClick: (id: string) => void }) {
  const [data, setData] = useState<KUSummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchClusterMemberKUs(clusterId, page, 10)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [clusterId, page])

  useEffect(() => { load() }, [load])

  return (
    <Table<KUSummary>
      columns={kuColumns}
      dataSource={data}
      rowKey="ku_id"
      loading={loading}
      size="small"
      pagination={{
        current: page,
        pageSize: 10,
        total,
        size: 'small',
        showTotal: (t) => <Typography.Text type="secondary">Total {t}</Typography.Text>,
        onChange: (p) => setPage(p),
      }}
      onRow={(r) => ({ onClick: () => onKUClick(r.ku_id), style: { cursor: 'pointer' } })}
    />
  )
}

function ClusterEntitiesTable({ clusterId, onEntityClick }: { clusterId: string; onEntityClick: (id: string) => void }) {
  const [data, setData] = useState<EntitySummary[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetchClusterRelatedEntities(clusterId)
      .then(setData)
      .finally(() => setLoading(false))
  }, [clusterId])

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
