"use client";

import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Analytics } from "@/types";

const C = { allow: "#1f9d55", block: "#d6336c", approval: "#d98b0b", grid: "#e1e5ec", axis: "#8a9bb8" };

function label(bucket: string): string {
  return bucket.includes("T") ? bucket.slice(11, 16) : bucket.slice(5);
}

export function ActivityChart({ data }: { data: Analytics["timeseries"] }) {
  const rows = data.map((d) => ({ ...d, label: label(d.bucket) }));
  return (
    <div className="h-64" role="img" aria-label="Actions over time by decision">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid stroke={C.grid} vertical={false} />
          <XAxis dataKey="label" stroke={C.axis} fontSize={11} tickLine={false} interval="preserveStartEnd" />
          <YAxis stroke={C.axis} fontSize={11} tickLine={false} allowDecimals={false} />
          <Tooltip />
          <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
          <Area type="monotone" dataKey="allowed" name="Allowed" stackId="1" stroke={C.allow} fill={C.allow} fillOpacity={0.25} />
          <Area type="monotone" dataKey="approvals" name="Needs approval" stackId="1" stroke={C.approval} fill={C.approval} fillOpacity={0.3} />
          <Area type="monotone" dataKey="blocked" name="Blocked" stackId="1" stroke={C.block} fill={C.block} fillOpacity={0.3} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function AgentActivityChart({ data }: { data: Analytics["agent_activity"] }) {
  return (
    <div className="h-64" role="img" aria-label="Actions per agent by decision">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 12, left: 24, bottom: 0 }}>
          <CartesianGrid stroke={C.grid} horizontal={false} />
          <XAxis type="number" stroke={C.axis} fontSize={11} allowDecimals={false} />
          <YAxis type="category" dataKey="agent" stroke={C.axis} fontSize={11} width={110} tickLine={false} />
          <Tooltip />
          <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="allowed" name="Allowed" stackId="a" fill={C.allow} />
          <Bar dataKey="approvals" name="Needs approval" stackId="a" fill={C.approval} />
          <Bar dataKey="blocked" name="Blocked" stackId="a" fill={C.block} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ReasonChart({ data }: { data: Analytics["block_reasons"] }) {
  return (
    <div className="h-64" role="img" aria-label="Top block reasons">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 12, left: 40, bottom: 0 }}>
          <CartesianGrid stroke={C.grid} horizontal={false} />
          <XAxis type="number" stroke={C.axis} fontSize={11} allowDecimals={false} />
          <YAxis type="category" dataKey="reason_code" stroke={C.axis} fontSize={10} width={170} tickLine={false} />
          <Tooltip />
          <Bar dataKey="count" name="Blocked actions" fill={C.block} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ToolChart({ data }: { data: Analytics["top_tools"] }) {
  return (
    <div className="h-64" role="img" aria-label="Most used tools">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid stroke={C.grid} vertical={false} />
          <XAxis dataKey="tool" stroke={C.axis} fontSize={10} tickLine={false} interval={0} angle={-20} textAnchor="end" height={60} />
          <YAxis stroke={C.axis} fontSize={11} allowDecimals={false} />
          <Tooltip />
          <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="total" name="Requests" fill="#0f766e" />
          <Bar dataKey="blocked" name="Blocked" fill={C.block} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
