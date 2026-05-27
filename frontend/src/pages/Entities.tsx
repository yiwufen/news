import { useEffect, useState, useCallback } from 'react'
import { Table, Input, Drawer, Tabs, Descriptions, Tag, Space, Typography, Select, Button, Modal, Form, Input as AntInput, message, Popconfirm } from 'antd'
import { PlusOutlined, MinusCircleOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { fetchEntities, fetchEntity, fetchEntityRelatedKUs, fetchEntityRelatedClusters, fetchEntityTypes, editEntity, mergeEntities, deleteEntity } from '../api/entities'
import type { EntitySummary, KUSummary, ClusterSummary } from '../api/types'

const columns: ColumnsType<EntitySummary> = [
  { title: 'Name', dataIndex: 'canonical_name', width: 300 },
  {
    title: 'Type',
    dataIndex: 'entity_type',
    width: 120,
    render: (v: string) => <Tag color="blue">{v || 'Unknown'}</Tag>,
  },
  {
    title: 'Updated',
    dataIndex: 'updated_at',
    width: 200,
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

const clusterColumns: ColumnsType<ClusterSummary> = [
  { title: 'Title', dataIndex: 'title', ellipsis: true },
  { title: 'Type', dataIndex: 'cluster_type', width: 160, ellipsis: true },
  {
    title: 'Members',
    dataIndex: 'member_count',
    width: 80,
    align: 'center',
  },
]

export default function Entities() {
  const [data, setData] = useState<EntitySummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [entityType, setEntityType] = useState('')
  const [typeOptions, setTypeOptions] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [mergeOpen, setMergeOpen] = useState(false)
  const [mergeSearchResults, setMergeSearchResults] = useState<EntitySummary[]>([])
  const [mergeSearching, setMergeSearching] = useState(false)
  const [editForm] = Form.useForm()
  const [mergeForm] = Form.useForm()
  const navigate = useNavigate()

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchEntities(page, pageSize, search, entityType)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, search, entityType])

  useEffect(() => { loadData() }, [loadData])

  useEffect(() => { fetchEntityTypes().then(setTypeOptions).catch(() => {}) }, [])

  useEffect(() => {
    const autoOpen = sessionStorage.getItem('autoOpenEntity')
    if (autoOpen) {
      sessionStorage.removeItem('autoOpenEntity')
      fetchEntity(autoOpen).then((d) => { setDetail(d); setDetailId(autoOpen); setDrawerOpen(true) }).catch(() => {})
    }
  }, [])

  const handleRowClick = async (record: EntitySummary) => {
    const d = await fetchEntity(record.entity_id)
    setDetail(d)
    setDetailId(record.entity_id)
    setDrawerOpen(true)
  }

  const openKU = (kuId: string) => {
    setDrawerOpen(false)
    sessionStorage.setItem('autoOpenKU', kuId)
    navigate('/knowledge-units')
  }

  const openCluster = (clusterId: string) => {
    setDrawerOpen(false)
    sessionStorage.setItem('autoOpenCluster', clusterId)
    navigate('/event-clusters')
  }

  const handleEdit = () => {
    if (!detail) return
    const aliases = (detail.aliases as string[]) || []
    const identifiers = (detail.identifiers as Record<string, string>) || {}
    const tags = (detail.tags as string[]) || []
    editForm.setFieldsValue({
      canonical_name: detail.canonical_name,
      entity_type: detail.entity_type || '',
      description: detail.description || '',
      aliases: aliases.length > 0 ? aliases : [''],
      identifierEntries: Object.entries(identifiers).length > 0
        ? Object.entries(identifiers).map(([k, v]) => ({ key: k, value: v }))
        : [{ key: '', value: '' }],
      tags: tags.length > 0 ? tags : [],
    })
    setEditOpen(true)
  }

  const handleEditSubmit = async () => {
    if (!detailId) return
    try {
      const values = await editForm.validateFields()
      const updates: Record<string, unknown> = {
        canonical_name: values.canonical_name,
        entity_type: values.entity_type,
        description: values.description,
      }
      // Filter out empty aliases
      const aliases = (values.aliases as string[] || []).filter((a: string) => a.trim())
      if (aliases.length > 0) updates.aliases = aliases

      // Convert identifier key-value pairs to dict
      const identifierEntries = (values.identifierEntries || []) as { key: string; value: string }[]
      const identifiers: Record<string, string> = {}
      for (const entry of identifierEntries) {
        if (entry.key.trim() && entry.value.trim()) {
          identifiers[entry.key.trim()] = entry.value.trim()
        }
      }
      if (Object.keys(identifiers).length > 0) updates.identifiers = identifiers

      // Tags
      const tags = (values.tags as string[] || []).filter((t: string) => t.trim())
      if (tags.length > 0) updates.tags = tags

      await editEntity(detailId, updates)
      message.success('Entity updated')
      setEditOpen(false)
      const d = await fetchEntity(detailId)
      setDetail(d)
      loadData()
    } catch {
      message.error('Update failed')
    }
  }

  const handleMergeSubmit = async () => {
    if (!detailId) return
    try {
      const { target_id } = await mergeForm.validateFields()
      await mergeEntities(detailId, target_id)
      message.success('Entities merged')
      setMergeOpen(false)
      setDrawerOpen(false)
      loadData()
    } catch {
      message.error('Merge failed')
    }
  }

  const handleMergeSearch = async (keyword: string) => {
    if (!keyword.trim()) {
      setMergeSearchResults([])
      return
    }
    setMergeSearching(true)
    try {
      const res = await fetchEntities(1, 20, keyword)
      setMergeSearchResults(res.items.filter((e) => e.entity_id !== detailId))
    } finally {
      setMergeSearching(false)
    }
  }

  const handleDelete = async () => {
    if (!detailId) return
    try {
      await deleteEntity(detailId)
      message.success('Entity deleted')
      setDrawerOpen(false)
      loadData()
    } catch {
      message.error('Delete failed')
    }
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
      label: 'Knowledge Units',
      children: (
        <RelatedKUsTable entityId={detailId!} onKUClick={openKU} />
      ),
    },
    {
      key: 'clusters',
      label: 'Event Clusters',
      children: (
        <RelatedClustersTable entityId={detailId!} onClusterClick={openCluster} />
      ),
    },
  ] : []

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="Search entities..."
          allowClear
          onSearch={setSearch}
          style={{ width: 300 }}
        />
        <Select
          placeholder="Entity type"
          allowClear
          style={{ width: 180 }}
          value={entityType || undefined}
          onChange={(v) => setEntityType(v || '')}
          options={typeOptions.map((t) => ({ value: t, label: t || 'Unknown' }))}
        />
      </Space>

      <Table<EntitySummary>
        columns={columns}
        dataSource={data}
        rowKey="entity_id"
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
        title={detail?.canonical_name as string || 'Entity Detail'}
        width={720}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        extra={
          <Space>
            <Button size="small" onClick={handleEdit}>Edit</Button>
            <Button size="small" onClick={() => { mergeForm.resetFields(); setMergeOpen(true) }}>Merge</Button>
            <Popconfirm title="Delete this entity?" onConfirm={handleDelete} okText="Delete" okType="danger">
              <Button size="small" danger>Delete</Button>
            </Popconfirm>
          </Space>
        }
      >
        {detail && <Tabs items={tabs} />}
      </Drawer>

      <Modal title="Edit Entity" open={editOpen} onOk={handleEditSubmit} onCancel={() => setEditOpen(false)} width={600}>
        <Form form={editForm} layout="vertical">
          <Form.Item name="canonical_name" label="Name"><AntInput /></Form.Item>
          <Form.Item name="entity_type" label="Type"><AntInput /></Form.Item>
          <Form.Item name="description" label="Description"><AntInput.TextArea rows={2} /></Form.Item>

          {/* Aliases — dynamic list */}
          <Typography.Text strong>Aliases</Typography.Text>
          <Form.List name="aliases">
            {(fields, { add, remove }) => (
              <>
                {fields.map((field) => (
                  <Space key={field.key} style={{ display: 'flex', marginBottom: 4 }} align="baseline">
                    <Form.Item {...field} noStyle><AntInput placeholder="Alias" style={{ width: 300 }} /></Form.Item>
                    <MinusCircleOutlined onClick={() => remove(field.name)} />
                  </Space>
                ))}
                <Button type="dashed" onClick={() => add()} block icon={<PlusOutlined />} size="small" style={{ marginBottom: 16 }}>
                  Add Alias
                </Button>
              </>
            )}
          </Form.List>

          {/* Identifiers — key-value pairs */}
          <Typography.Text strong>Identifiers</Typography.Text>
          <Form.List name="identifierEntries">
            {(fields, { add, remove }) => (
              <>
                {fields.map((field) => (
                  <Space key={field.key} style={{ display: 'flex', marginBottom: 4 }} align="baseline">
                    <Form.Item name={[field.name, 'key']} noStyle><AntInput placeholder="Key (e.g. ticker)" style={{ width: 140 }} /></Form.Item>
                    <Form.Item name={[field.name, 'value']} noStyle><AntInput placeholder="Value (e.g. 002594.SZ)" style={{ width: 200 }} /></Form.Item>
                    <MinusCircleOutlined onClick={() => remove(field.name)} />
                  </Space>
                ))}
                <Button type="dashed" onClick={() => add()} block icon={<PlusOutlined />} size="small" style={{ marginBottom: 16 }}>
                  Add Identifier
                </Button>
              </>
            )}
          </Form.List>

          {/* Tags */}
          <Form.Item name="tags" label="Tags">
            <Select mode="tags" placeholder="Add tags" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={`Merge "${detail?.canonical_name}" into...`} open={mergeOpen} onOk={handleMergeSubmit} onCancel={() => setMergeOpen(false)}>
        <Form form={mergeForm} layout="vertical">
          <Form.Item name="target_id" label="Target Entity" rules={[{ required: true, message: 'Please select a target entity' }]}>
            <Select
              showSearch
              placeholder="Search entity name..."
              filterOption={false}
              onSearch={handleMergeSearch}
              loading={mergeSearching}
              notFoundContent={mergeSearching ? 'Searching...' : 'Type to search'}
              options={mergeSearchResults.map((e) => ({
                value: e.entity_id,
                label: `${e.canonical_name} (${e.entity_type || 'Unknown'}) — ${e.entity_id}`,
              }))}
            />
          </Form.Item>
        </Form>
        <Typography.Text type="secondary">
          The current entity will be absorbed into the target. All aliases, identifiers, and KU references will be merged.
        </Typography.Text>
      </Modal>
    </div>
  )
}

function RelatedKUsTable({ entityId, onKUClick }: { entityId: string; onKUClick: (id: string) => void }) {
  const [data, setData] = useState<KUSummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchEntityRelatedKUs(entityId, page, 10)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [entityId, page])

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

function RelatedClustersTable({ entityId, onClusterClick }: { entityId: string; onClusterClick: (id: string) => void }) {
  const [data, setData] = useState<ClusterSummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchEntityRelatedClusters(entityId, page, 10)
      setData(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [entityId, page])

  useEffect(() => { load() }, [load])

  return (
    <Table<ClusterSummary>
      columns={clusterColumns}
      dataSource={data}
      rowKey="cluster_id"
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
      onRow={(r) => ({ onClick: () => onClusterClick(r.cluster_id), style: { cursor: 'pointer' } })}
    />
  )
}
