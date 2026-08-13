//    Ferrastra - CPU-first native graphics product engine
//    Copyright (C) 2025  Artificial Sweetener and contributors
//
//    This program is free software: you can redistribute it and/or modify
//    it under the terms of the GNU General Public License as published by
//    the Free Software Foundation, either version 3 of the License, or
//    (at your option) any later version.
//
//    This program is distributed in the hope that it will be useful,
//    but WITHOUT ANY WARRANTY; without even the implied warranty of
//    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
//    GNU General Public License for more details.
//
//    You should have received a copy of the GNU General Public License
//    along with this program.  If not, see <https://www.gnu.org/licenses/>.

//! Contract proof for exact cropped and phase-stable axis-aligned Lanczos3 views.

#[path = "support/lanczos3_fixture.rs"]
#[allow(dead_code, reason = "the whole-raster contract uses the other shared fixtures")]
mod fixture;
#[path = "support/lanczos3_oracle.rs"]
#[allow(dead_code, reason = "the whole-raster contract uses the other shared oracle entry")]
mod oracle;

use fixture::{ViewCase, execute_view_region, full_region, patterned_source, rect};
use oracle::OracleEdge;

#[test]
fn cropped_fractional_grid_matches_the_independent_oracle() {
    let source_size = (9, 7);
    let destination_size = (7, 5);
    let first_center = (1.25, 0.4);
    let source_step = (0.75, 1.1);
    let source = patterned_source(source_size);
    let actual = execute_view_region(
        &source,
        ViewCase {
            source_size,
            destination_size,
            first_center,
            source_step,
            region: full_region(destination_size),
            edge: "clamp",
            space: "srgb_linear",
        },
    );
    let expected = oracle::sample_view(
        &source,
        source_size,
        destination_size,
        first_center,
        source_step,
        OracleEdge::Clamp,
        true,
    );

    fixture::assert_pixels_within(&actual, &expected, 1);
}

#[test]
fn independently_requested_tiles_keep_the_global_sampling_phase() {
    let source_size = (12, 9);
    let destination_size = (11, 8);
    let source = patterned_source(source_size);
    let case = ViewCase {
        source_size,
        destination_size,
        first_center: (-0.2, 0.65),
        source_step: (0.8, 1.25),
        region: full_region(destination_size),
        edge: "reflect",
        space: "srgb_encoded",
    };
    let complete = execute_view_region(&source, case);
    let mut tiled = vec![0_u8; destination_size.0 * destination_size.1 * 4];
    for region in [rect(0, 0, 5, 3), rect(5, 0, 6, 3), rect(0, 3, 5, 5), rect(5, 3, 6, 5)] {
        let tile = execute_view_region(&source, ViewCase { region, ..case });
        fixture::place_tile(&mut tiled, destination_size.0, region, &tile);
    }

    assert_eq!(tiled, complete);
}

#[test]
fn sampled_view_identity_grid_preserves_exact_source_bytes() {
    let source_size = (5, 4);
    let source = patterned_source(source_size);
    let actual = execute_view_region(
        &source,
        ViewCase {
            source_size,
            destination_size: source_size,
            first_center: (0.0, 0.0),
            source_step: (1.0, 1.0),
            region: full_region(source_size),
            edge: "transparent",
            space: "srgb_linear",
        },
    );

    assert_eq!(actual, source);
}
