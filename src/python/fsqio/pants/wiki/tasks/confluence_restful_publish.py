# coding=utf-8
# Copyright 2018 Foursquare Labs Inc. All Rights Reserved.

from __future__ import absolute_import, division, print_function

import os
import shutil
import textwrap

from pants.base.exceptions import TaskError
from pants.build_graph.resources import Resources
from pants.contrib.confluence.tasks.confluence_publish import ConfluencePublish
from pants.contrib.confluence.util.confluence_util import ConfluenceError
from pants.util.memo import memoized_property

from fsqio.pants.wiki.subsystems.confluence_subsystem import ConfluenceSubsystem
from fsqio.pants.wiki.util.confluence_cloud import ConfluenceCloud


class ConfluenceRestfulPublish(ConfluencePublish):
  """Rest client for ConfluenceCloud, for use with hosted wikis."""

  @classmethod
  def subsystem_dependencies(cls):
    return super(ConfluenceRestfulPublish, cls).subsystem_dependencies() + (ConfluenceSubsystem,)

  @memoized_property
  def confluence_subsystem(self):
    return ConfluenceSubsystem.global_instance()

  @memoized_property
  def email_domain(self):
    return self.confluence_subsystem.email_domain

  @memoized_property
  def url(self):
    return self.confluence_subsystem.wiki_url

  @memoized_property
  def force(self):
    return self.get_options().force

  @memoized_property
  def open(self):
    return self.get_options().open

  @memoized_property
  def user(self):
    return self.get_options().user

  @classmethod
  def register_options(cls, register):
    # TODO(mateo): These options and the init are inlined from ConfluencePublish because
    # that file set properties inside the init and cannot be decoupled from them.
    # Moving those to properties and other contracts of being a good citizen superclass.
    # pylint: disable=bad-super-call
    super(ConfluencePublish, cls).register_options(register)
    register(
      '--user',
      help='Confluence user name, defaults to unix user.',
    )
    register(
      '--force',
      type=bool,
      help='Force publish the page even if its contents is identical to the contents on confluence.',
    )
    register(
      '--open',
      type=bool,
      help='Attempt to open the published confluence wiki page in a browser.',
    )

  def __init__(self, *args, **kwargs):
    self._wiki = None
    # NOTE(mateo): Purposeful abuse of the super call to avoid legacy practices in the upstream task.
    # pylint: disable=bad-super-call
    super(ConfluencePublish, self).__init__(*args, **kwargs)

  def api(self):
    return 'confluence2'

  def publish_page(self, address, space, title, content, parent=None):
    body = textwrap.dedent('''

      <!-- DO NOT EDIT - generated by pants from {} -->

      {}
      ''').strip().format(address, content)

    pageopts = dict(
      versionComment='updated by pants!'
    )
    wiki = self.login()
    existing = wiki.getpage(space, title)
    if existing:
      # NOTE: Disabled the no-op detection for publish (no consequences on user build time at all).
      # We need the page to be generated before we attach resources.
      # TODO(mateo): Restore or deep-six after we land on a solution for displaying inline attachments.
      #
      # if not self.force and wiki.get_content_value(existing).strip() == body.strip():
      #   return

      pageopts['id'] = existing['id']
      pageopts['version'] = existing['version']

    try:
      page = wiki.create_html_page(space, title, body, parent, **pageopts)
    except ConfluenceError as e:
      raise TaskError('Failed to update confluence: {}'.format(e))

    # Copy any resource files into the html dist of the dependent page target.
    # This is not required for Confluence attachment - if the final image tag
    # doesn't work for both markdown and confluence, maybe just pass the source location to the API and otherwise
    # leave the filesystem alone
    page_target = self.context.build_graph.get_target(address)
    outdir = os.path.join(self.get_options().pants_distdir, 'markdown', 'html')
    page_outdir = os.path.join(outdir, page_target.sources_relative_to_target_base().rel_root)

    for target in page_target.dependencies:
      if isinstance(target, Resources):
        # Copy next to rendered HTML in dist for local use and attach to newly published page for the wiki.
        for resource_file in target.sources_relative_to_buildroot():
          shutil.copy2(resource_file, page_outdir)
          wiki.addattachment(page, resource_file)
    return wiki.get_url(page)

  def login(self):
    if not self._wiki:
      flagged = self.get_options().is_flagged('user')
      # Use the passed user - first checking to see where the default is applied
      # User is seeded by Pants but the options system does not recognize seeded values as being defaults.
      user = self.user if flagged else self.user + self.email_domain
      try:
        self._wiki = ConfluenceCloud.login(self.url, user, self.api())
      except ConfluenceError as e:
        raise TaskError('Failed to login to confluence: {}'.format(e))
    return self._wiki
