import { useEffect, useState, useCallback } from 'react'
import { Table, Input, Drawer, Descriptions, Tag, Space } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { fetchArticles, fetchArticle } from '../api/articles'
import type { ArticleSummary } from '../api/types'

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

export default function Articles() {
  const [data, setData] = useState<ArticleSummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchArticles(page, pageSize, search)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, search])

  useEffect(() => { loadData() }, [loadData])

  const handleRowClick = async (record: ArticleSummary) => {
    const d = await fetchArticle(record.doc_id)
    setDetail(d)
    setDrawerOpen(true)
  }

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="Search articles..."
          allowClear
          onSearch={setSearch}
          style={{ width: 300 }}
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
        {detail && (
          <Descriptions column={1} bordered size="small">
            {Object.entries(detail).map(([key, value]) => (
              <Descriptions.Item key={key} label={key}>
                {typeof value === 'string' && value.length > 500
                  ? value.substring(0, 500) + '...'
                  : String(value ?? '')}
              </Descriptions.Item>
            ))}
          </Descriptions>
        )}
      </Drawer>
    </div>
  )
}
