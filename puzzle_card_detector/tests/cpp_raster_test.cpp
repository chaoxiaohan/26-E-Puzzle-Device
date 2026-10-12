#include <iostream>
#include <random>
#include <stdexcept>
#include "../rectangle_solver.cpp"

static void verify(const std::vector<Point>& polygon, int width, int height) {
    Candidate actual = rasterize(polygon, width, height);
    std::vector<std::uint64_t> mask(actual.mask.size(), 0);
    std::vector<std::uint64_t> core(actual.core.size(), 0);
    int area = 0;
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            if (point_in_polygon(x + 0.5, y + 0.5, polygon)) {
                set_bit(mask, y * width + x);
                ++area;
            }
        }
    }
    for (int y = 1; y < height - 1; ++y) {
        for (int x = 1; x < width - 1; ++x) {
            bool keep = true;
            for (int dy = -1; dy <= 1; ++dy) {
                for (int dx = -1; dx <= 1; ++dx) {
                    keep = keep && get_bit(mask, (y + dy) * width + x + dx);
                }
            }
            if (keep) {
                set_bit(core, y * width + x);
            }
        }
    }
    if (actual.area != area || actual.mask != mask || actual.core != core) {
        throw std::runtime_error("Raster mask, area or 3x3 erosion differs from pixel reference");
    }
}

int main() {
    int cases = 0;
    std::mt19937 random(20261012);
    for (int width : {51, 64, 65, 83, 127, 128, 129}) {
        for (int height : {37, 64, 79}) {
            double centre = width * 0.5;
            for (double offset : {-2.5, 0.0, 0.5, std::nextafter(0.5, 1.0)}) {
                verify({{offset, offset}, {width - 0.5, offset},
                        {width - 0.5, height - 0.5}, {offset, height - 0.5}}, width, height);
                verify({{offset, offset}, {centre, height - 0.5},
                        {width - 0.5, offset}}, width, height);
                verify({{offset, offset}, {width - 0.5, offset},
                        {centre, height * 0.4}, {width - 0.5, height - 0.5},
                        {offset, height - 0.5}}, width, height);
                cases += 3;
            }
            for (int sample = 0; sample < 30; ++sample) {
                std::vector<Point> polygon;
                for (int vertex = 0; vertex < 3 + sample % 3; ++vertex) {
                    polygon.push_back({double(random() % (width * 100)) / 100.0 - 2.5,
                                       double(random() % (height * 100)) / 100.0 - 2.5});
                }
                verify(polygon, width, height);
                ++cases;
            }
        }
    }
    std::vector<std::vector<Point>> pieces = {
        {{424, 127}, {455, 224}, {539, 197}},
        {{367, 150}, {204, 166}, {236, 240}, {341, 202}},
        {{122, 315}, {183, 387}, {332, 319}, {335, 296}, {186, 267}},
        {{516, 331}, {472, 277}, {369, 366}, {509, 386}},
    };
    double area = 0.0;
    for (const auto& piece : pieces) {
        area += std::abs(polygon_area(piece));
    }
    for (double fill : {0.96, 0.72}) {
        for (double ratio : {1.0, 2.4}) {
            int width = int(std::lround(std::sqrt(6000.0 * ratio)));
            int height = int(std::lround(6000.0 / width));
            for (auto polygon : pieces) {
                if (polygon_area(polygon) < 0.0) {
                    std::reverse(polygon.begin(), polygon.end());
                }
                double scale = std::sqrt(6000.0 * fill / area);
                for (auto& point : polygon) {
                    point.x *= scale;
                    point.y *= scale;
                }
                for (const auto& candidate : generate_candidates(polygon, width, height, 4, true)) {
                    verify(candidate.polygon, width, height);
                    ++cases;
                }
            }
        }
    }
    std::cout << "RASTER_REFERENCE_OK cases=" << cases << std::endl;
}
