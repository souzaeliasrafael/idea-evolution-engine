import { DiscoveryDetail } from "@/components/discovery-detail";

export default async function DiscoveryCampaignPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <DiscoveryDetail campaignId={id} />;
}
