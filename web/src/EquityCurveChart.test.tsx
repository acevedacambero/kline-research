import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { EquityCurveChart } from "./EquityCurveChart";

it("renders the P8 equity curve and its accessible summary", () => {
  const { container } = render(
    <EquityCurveChart
      points={[
        { date: "2024-01-02", value: 1 },
        { date: "2024-02-01", value: 1.08 },
        { date: "2024-03-01", value: 1.03 },
      ]}
    />,
  );

  expect(screen.getByLabelText("P8 组合净值曲线")).toBeInTheDocument();
  expect(screen.getByText("1.030")).toBeInTheDocument();
  expect(screen.getByText(/2024-01-02 → 2024-03-01/)).toBeInTheDocument();
  expect(
    container.querySelector("polyline")?.getAttribute("points"),
  ).toBeTruthy();
});

it("does not render an empty curve", () => {
  const { container } = render(<EquityCurveChart points={[]} />);
  expect(container).toBeEmptyDOMElement();
});
