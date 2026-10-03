import { fireEvent, render, screen } from "@testing-library/react";
import { Pagination, RuleChip, SocBar, Toggle } from "@/components/ui";
import { ReadinessBadge } from "@/components/status";

describe("UI primitives", () => {
  it("SocBar exposes SoC and requirement to assistive tech", () => {
    render(<SocBar soc={42} required={72} />);
    expect(screen.getByRole("img")).toHaveAccessibleName("State of charge 42%, required 72%");
    expect(screen.getByText("42%")).toBeInTheDocument();
  });

  it("Toggle is a switch that reports its state", () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} onChange={onChange} label="Tariff optimisation" />);
    const sw = screen.getByRole("switch", { name: "Tariff optimisation" });
    expect(sw).toHaveAttribute("aria-checked", "false");
    fireEvent.click(sw);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("Pagination disables navigation at the bounds", () => {
    const onPage = vi.fn();
    render(<Pagination page={1} pageSize={25} total={60} onPage={onPage} />);
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(onPage).toHaveBeenCalledWith(2);
    expect(screen.getByText("1–25 of 60")).toBeInTheDocument();
  });

  it("rule chips carry the rule text and readiness badges a text label", () => {
    render(
      <>
        <RuleChip code="R4" />
        <ReadinessBadge value="at_risk" />
      </>,
    );
    expect(screen.getByTitle(/lower-cost window/)).toHaveTextContent("R4");
    expect(screen.getByText("At risk")).toBeInTheDocument();
  });
});
