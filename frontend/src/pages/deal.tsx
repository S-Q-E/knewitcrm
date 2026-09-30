import { useNavigate, useParams } from "react-router-dom";

import { DealDetail } from "@/components/deals/detail";
import { Button } from "@/components/ui/button";

export function DealPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  if (!id) {
    navigate("/deals", { replace: true });
    return null;
  }
  return (
    <div className="mx-auto max-w-5xl">
      <Button variant="ghost" size="sm" className="mb-3" onClick={() => navigate("/deals")}>
        ← К сделкам
      </Button>
      <DealDetail dealId={id} />
    </div>
  );
}
