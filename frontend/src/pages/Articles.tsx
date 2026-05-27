import { useEffect, useState, useCallback } from 'react'
import { Table, Input, Drawer, Tabs, Descriptions, Tag, Space, Typography, DatePicker } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { fetchArticles, fetchArticle, fetchArticleRelatedKUs, fetchArticleRelatedEntities } from '../api/articles'
import type { ArticleSummary, KUSummary, EntitySummary } from '../api/types'

const { RangePicker } = DatePicker

const tierColors: Record<number, string> = {
  1: 'green',
  2: 'blue',
  3: 'orange',
}

const columns: ColumnsType<ArticleSummary> = [
  { title: 'Title', dataIndex: 'title', ellipsis: true },
  { title: 'Source', dataIndex: 'source_name', width: 120 },
  {
    title: 'Category',
    dataIndex: 'category',
    width: 180,
    render: (v: string) => <Tag>{v}</Tag>,
  },
  {
    title: 'Tier',
    dataIndex: 'credibility_tier',
    width: 70,
    align: 'center',
    render: (v: number) => <Tag color={tierColors[v] || 'default'}>{v}</Tag>,
  },
  {
    title: 'Published',
    dataIndex: 'publish_time',
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

export default function Articles() {
  const [data, setData] = useState<ArticleSummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const navigate = useNavigate()

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchArticles(page, pageSize, search, '', dateFrom, dateTo)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, search, dateFrom, dateTo])

  useEffect(() => { loadData() }, [loadData])

  const handleRowClick = async (record: ArticleSummary) => {
    const d = await fetchArticle(record.doc_id)
    setDetail(d)
    setDetailId(record.doc_id)
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

  const tabs = detail ? [
    {
      key: 'info',
      label: 'Basic Info',
      children: (
        <Descriptions column={1} bordered size="small">
          {Object.entries(detail).map(([key, value]) => (
            <Descriptions.Item key={key} label={key}>
              {typeof value === 'string' && value.length > 500
                ? value.substring(0, 500) + '...'
                : String(value ?? '')}
            </Descriptions.Item>
          ))}
        </Descriptions>
      ),
    },
    {
      key: 'kus',
      label: 'Knowledge Units',
      children: (
        <ArticleKUsTable docId={detailId!} onKUClick={openKU} />
      ),
    },
    {
      key: 'entities',
      label: 'Entities',
      children: (
        <ArticleEntitiesTable docId={detailId!} onEntityClick={openEntity} />
      ),
    },
  ] : []

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="Search articles..."
          allowClear
          onSearch={setSearch}
          style={{ width: 300 }}
        />
        <RangePicker
          placeholder={['Start date', 'End date']}
          onChange={(dates) => {
            if (dates && dates[0] && dates[1]) {
              setDateFrom(dates[0].format('YYYY-MM-DD'))
              setDateTo(dates[1].format('YYYY-MM-DD'))
            } else {
              setDateFrom('')
              setDateTo('')
            }
          }}
        />
      </Space>

      <Table<ArticleSummary>
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
        onRow={(record) => ({ onClick: () => handleRowClick(record), style: { cursor: 'pointer' } })}
        size="small"
      />

      <Drawer
        title="Article Detail"
        width={720}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        {detail && <Tabs items={tabs} />}
      </Drawer>
    </div>
  )
}

function ArticleKUsTable({ docId, onKUClick }: { docId: string; onKUClick: (id: string) => void }) {
  const [data, setData] = useState<KUSummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchArticleRelatedKUs(docId, page, 10)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [docId, page])

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

function ArticleEntitiesTable({ docId, onEntityClick }: { docId: string; onEntityClick: (id: string) => void }) {
  const [data, setData] = useState<EntitySummary[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetchArticleRelatedEntities(docId)
      .then(setData)
      .finally(() => setLoading(false))
  }, [docId])

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
